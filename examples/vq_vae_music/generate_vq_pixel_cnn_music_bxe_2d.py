import argparse
import tensorflow as tf
import numpy as np
from tfbldr.datasets import save_image_array
from tfbldr.datasets import notes_to_midi
from tfbldr.datasets import midi_to_notes
from collections import namedtuple
import sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import copy
from tfbldr.datasets import quantized_to_pretty_midi

from decode import decode_measure

parser = argparse.ArgumentParser()
parser.add_argument('pixelcnn_model', nargs=1, default=None)
parser.add_argument('vqvae_model', nargs=1, default=None)
parser.add_argument('--seed', dest='seed', type=int, default=1999)
args = parser.parse_args()
vqvae_model_path = args.vqvae_model[0]
pixelcnn_model_path = args.pixelcnn_model[0]

num_to_generate = 1000
num_each = 64
random_state = np.random.RandomState(args.seed)

d1 = np.load("music_data_jos.npz")
flat_images = np.array([mai for amai in copy.deepcopy(d1['measures_as_images']) for mai in amai])
image_data = flat_images

# times 0 to ensure NO information leakage
sample_image_data = 0. * image_data 
d2 = np.load("vq_vae_encoded_music_jos_2d.npz")

# use these to generate
labels = d2["labels"]
flat_idx = d2["flat_idx"]
sample_labels = labels[-1000:]

random_state = np.random.RandomState(2000)
def sample_gumbel(logits, temperature=1.):
    noise = random_state.uniform(1E-5, 1. - 1E-5, np.shape(logits))
    return np.argmax(logits / float(temperature) - np.log(-np.log(noise)), axis=-1)

config = tf.ConfigProto(
    device_count={'GPU': 0}
)

with tf.Session(config=config) as sess1:
    saver = tf.train.import_meta_graph(pixelcnn_model_path + '.meta')
    saver.restore(sess1, pixelcnn_model_path)
    fields = ['images',
              'labels',
              'x_tilde']
    vs = namedtuple('Params', fields)(
        *[tf.get_collection(name)[0] for name in fields]
    )
    y = sample_labels[:num_to_generate]

    pix_z = np.zeros((num_to_generate, 6, 6))
    for i in range(pix_z.shape[1]):
        for j in range(pix_z.shape[2]):
            print("Sampling v completion pixel {}, {}".format(i, j))
            feed = {vs.images: pix_z[..., None],
                    vs.labels: y}
            outs = [vs.x_tilde]
            r = sess1.run(outs, feed_dict=feed)
            x_rec = sample_gumbel(r[-1])

            for k in range(pix_z.shape[0]):
                pix_z[k, i, j] = float(x_rec[k, i, j])
sess1.close()
tf.reset_default_graph()

with tf.Session(config=config) as sess2:
    saver = tf.train.import_meta_graph(vqvae_model_path + '.meta')
    saver.restore(sess2, vqvae_model_path)
    """
    # test by faking like we sampled these from pixelcnn
    d = np.load("vq_vae_encoded_mnist.npz")
    valid_z_i = d["valid_z_i"]
    """
    fields = ['images',
              'bn_flag',
              'z_e_x',
              'z_q_x',
              'z_i_x',
              'x_tilde']
    vs = namedtuple('Params', fields)(
        *[tf.get_collection(name)[0] for name in fields]
    )
    x = image_data[:num_to_generate]
    z_i = pix_z[:num_to_generate]
    # again multiply by 0 to avoid information leakage
    feed = {vs.images: 0. * x,
            vs.z_i_x: z_i,
            vs.bn_flag: 1.}
    outs = [vs.x_tilde]
    r = sess2.run(outs, feed_dict=feed)
    x_rec = r[-1]

# binarize the predictions
x_rec[x_rec > 0.5] = 1.
x_rec[x_rec <= 0.5] = 0.

full_chords_kv = d2["full_chords_kv"]
label_to_lcr_kv = d2["label_to_lcr_kv"]
basic_chords_kv = d2["basic_chords_kv"]
full_chords_kv = d2["full_chords_kv"]
# many of these need to choose
scalenotes = d2["scalenotes"]

label_to_lcr = {int(k): tuple([int(iv) for iv in v.split(",")]) for k, v in label_to_lcr_kv}
full_chords_lu = {k: int(v) for k, v in full_chords_kv}
basic_chords_lu = {k: int(v) for k, v in full_chords_kv}

flat_scalenotes = [sn for sg in copy.deepcopy(d2["scalenotes"]) for sn in sg]
sample_scalenotes = flat_scalenotes[-1000:]

"""
# find some start points
for n in range(len(sample_labels)):
    lcr_i = label_to_lcr[sample_labels[n, 0]]
    if lcr_i[0] == 0:
        print(n) 
"""
# 16 44 117 119 143 151 206 242 267 290 308 354 380 410 421 456 517 573 598 622 638 663 676 688 715 725 749 752 820 851 866 922

# start at 16 since that's the start of a chord sequence (could choose any of the numbers above)
for offset in [16, 44, 308, 421, 517, 752, 866]:
    print("sampling offset {}".format(offset))
    x_rec_i = x_rec[offset:offset + num_each]
    save_image_array(x_rec_i, "pixel_cnn_gen_{}.png".format(offset))

    sample_flat_idx = flat_idx[-1000:]

    p = sample_flat_idx[offset:offset + num_each]
    note_to_norm_kv = d2["note_to_norm_kv"]
    midi_to_norm_kv = d2["midi_to_norm_kv"]

    # EEE more than 1 value maps to 0 in these kv lookups!
    midi_to_norm_lu = {int(k): int(v) + 1 if k != 0 else 0 for k, v in midi_to_norm_kv[p[0][0]]}
    norm_to_midi_lu = {v: k for k, v in midi_to_norm_lu.items()}
    note_to_norm_lu = {k: int(v) + 1 if k != "R" else 0 for k, v in note_to_norm_kv[p[0][0]]}
    norm_to_note_lu = {int(v): k for k, v in note_to_norm_lu.items()}

    prev = None
    decoded_satb_midi = [[], [], [], []]
    decoded_satb_notes = [[], [], [], []]
    for n in range(len(x_rec_i)):
        # 48 x 48 measure in
        satb = decode_measure(x_rec_i[n][..., 0], prev)
        prev = [satb[i][-1] for i in range(len(satb))]
        for i in range(len(satb)):
            decoded_satb_midi_s = [norm_to_midi_lu[j] if j in norm_to_midi_lu else 0 for j in satb[i]]
            decoded_satb_note_s = [norm_to_note_lu[j] if j in norm_to_note_lu else 0 for j in satb[i]]
            decoded_satb_midi[i].extend(decoded_satb_midi_s)
            decoded_satb_notes[i].extend(decoded_satb_note_s)

    quantized_to_pretty_midi([decoded_satb_midi],
                             0.25,
                             save_dir="samples",
                             name_tag="sample_{}".format(offset) + "_{}.mid",
                             default_quarter_length=220,
                             voice_params="piano")
    print("saved sample {}".format(offset))
from IPython import embed; embed(); raise ValueError()
