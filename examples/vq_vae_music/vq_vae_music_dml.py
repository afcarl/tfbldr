from tfbldr.datasets import fetch_mnist
from tfbldr.nodes import Conv2d
from tfbldr.nodes import ConvTranspose2d
from tfbldr.nodes import VqEmbedding
from tfbldr.nodes import BatchNorm2d
from tfbldr.nodes import ReLU
from tfbldr.nodes import DiscreteMixtureOfLogistics
from tfbldr.nodes import DiscreteMixtureOfLogisticsCost
from tfbldr.nodes import BernoulliCrossEntropyCost
from tfbldr.datasets import list_iterator
from tfbldr import get_params_dict
from tfbldr import run_loop
import tensorflow as tf
import numpy as np
from collections import namedtuple

d = np.load("music_data.npz")
#mnist = fetch_mnist()
image_data = 2 * d["measures"] - 1.
shuffle_random = np.random.RandomState(112)
shuffle_random.shuffle(image_data)
# save last 1k to validate on
train_image_data = image_data[:-1000]
val_image_data = image_data[-1000:]
train_itr_random_state = np.random.RandomState(1122)
val_itr_random_state = np.random.RandomState(1)
train_itr = list_iterator([train_image_data], 64, random_state=train_itr_random_state)
val_itr = list_iterator([val_image_data], 64, random_state=val_itr_random_state)

random_state = np.random.RandomState(1999)
l1_dim = (64, 4, 4, [1, 2, 2, 1])
l2_dim = (128, 4, 4, [1, 2, 2, 1])
l3_dim = (257, 4, 4, [1, 2, 2, 1])
l4_dim = (256, 4, 4, [1, 2, 2, 1])
l5_dim = (257, 1, 1, [1, 1, 1, 1])
embedding_dim = 256
n_components = 10
dmol_proj = 64
l_dims = [l1_dim, l2_dim, l3_dim, l4_dim, l5_dim]
stride_div = np.prod([ld[-1] for ld in l_dims])
ebpad = [0, 4 // 2 - 1, 4 // 2 - 1, 0]
dbpad = [0, 4 // 2 - 1, 4 // 2 - 1, 0]

def create_encoder(inp, bn_flag):
    l1 = Conv2d([inp], [3], l_dims[0][0], kernel_size=l_dims[0][1:3], name="enc1",
                strides=l_dims[0][-1],
                border_mode=ebpad,
                random_state=random_state)
    bn_l1 = BatchNorm2d(l1, bn_flag, name="bn_enc1")
    r_l1 = ReLU(bn_l1)

    l2 = Conv2d([r_l1], [l_dims[0][0]], l_dims[1][0], kernel_size=l_dims[1][1:3], name="enc2",
                strides=l_dims[1][-1],
                border_mode=ebpad,
                random_state=random_state)
    bn_l2 = BatchNorm2d(l2, bn_flag, name="bn_enc2")
    r_l2 = ReLU(bn_l2)

    l3 = Conv2d([r_l2], [l_dims[1][0]], l_dims[2][0], kernel_size=l_dims[2][1:3], name="enc3",
                strides=l_dims[2][-1],
                border_mode=ebpad,
                random_state=random_state)
    bn_l3 = BatchNorm2d(l3, bn_flag, name="bn_enc3")
    r_l3 = ReLU(bn_l3)

    l4 = Conv2d([r_l3], [l_dims[2][0]], l_dims[3][0], kernel_size=l_dims[3][1:3], name="enc4",
                strides=l_dims[3][-1],
                border_mode=ebpad,
                random_state=random_state)
    bn_l4 = BatchNorm2d(l4, bn_flag, name="bn_enc4")
    r_l4 = ReLU(bn_l4)

    l5 = Conv2d([r_l4], [l_dims[3][0]], l_dims[4][0], kernel_size=l_dims[4][1:3], name="enc5",
                random_state=random_state)
    bn_l5 = BatchNorm2d(l5, bn_flag, name="bn_enc5")
    return bn_l5


def create_decoder(latent, bn_flag):
    l1 = Conv2d([latent], [l_dims[-1][0]], l_dims[-2][0], kernel_size=l_dims[-1][1:3], name="dec1",
                random_state=random_state)
    bn_l1 = BatchNorm2d(l1, bn_flag, name="bn_dec1")
    r_l1 = ReLU(bn_l1)

    l2 = ConvTranspose2d([r_l1], [l_dims[-2][0]], l_dims[-3][0], kernel_size=l_dims[-2][1:3], name="dec2",
                         strides=l_dims[-2][-1],
                         border_mode=dbpad,
                         random_state=random_state)
    bn_l2 = BatchNorm2d(l2, bn_flag, name="bn_dec2")
    r_l2 = ReLU(bn_l2)

    l3 = ConvTranspose2d([r_l2], [l_dims[-3][0]], l_dims[-4][0], kernel_size=l_dims[-3][1:3], name="dec3",
                         strides=l_dims[-3][-1],
                         border_mode=dbpad,
                         random_state=random_state)
    bn_l3 = BatchNorm2d(l3, bn_flag, name="bn_dec3")
    r_l3 = ReLU(bn_l3)

    l4 = ConvTranspose2d([r_l3], [l_dims[-4][0]], l_dims[-5][0], kernel_size=l_dims[-4][1:3], name="dec4",
                         strides=l_dims[-4][-1],
                         border_mode=dbpad,
                         random_state=random_state)
    bn_l4 = BatchNorm2d(l4, bn_flag, name="bn_dec4")
    r_l4 = ReLU(bn_l4)


    l5 = ConvTranspose2d([r_l4], [l_dims[-5][0]], dmol_proj, kernel_size=l_dims[-5][1:3], name="dec5",
                         strides=l_dims[-5][-1],
                         border_mode=dbpad,
                         random_state=random_state)
    l5_mix, l5_means, l5_lin_scales, l5_coeffs = DiscreteMixtureOfLogistics([l5], [dmol_proj], n_output_channels=3, compute_channel_correlations=True, n_components=n_components, name="d_out", random_state=random_state)
    return l5_mix, l5_means, l5_lin_scales, l5_coeffs


def create_vqvae(inp, bn):
    z_e_x = create_encoder(inp, bn)
    z_q_x, z_i_x, z_nst_q_x, emb = VqEmbedding(z_e_x, l_dims[-1][0], embedding_dim, random_state=random_state, name="embed")
    x_tilde_mix, x_tilde_means, x_tilde_lin_scales, x_tilde_coeffs = create_decoder(z_q_x, bn)
    return x_tilde_mix, x_tilde_means, x_tilde_lin_scales, x_tilde_coeffs, z_e_x, z_q_x, z_i_x, z_nst_q_x, emb


def create_graph():
    graph = tf.Graph()
    with graph.as_default():
        images = tf.placeholder(tf.float32, shape=[None, 48, 48, 3])
        bn_flag = tf.placeholder_with_default(tf.zeros(shape=[]), shape=[])
        x_tilde_mix, x_tilde_means, x_tilde_lin_scales, x_tilde_coeffs, z_e_x, z_q_x, z_i_x, z_nst_q_x, z_emb = create_vqvae(images, bn_flag)
        rec_loss = tf.reduce_mean(DiscreteMixtureOfLogisticsCost(x_tilde_mix, x_tilde_means, x_tilde_lin_scales, images, 256, n_output_channels=3, channel_correlations=x_tilde_coeffs))
        #rec_loss = tf.reduce_mean(BernoulliCrossEntropyCost(x_tilde, images))
        vq_loss = tf.reduce_mean(tf.square(tf.stop_gradient(z_e_x) - z_nst_q_x))
        commit_loss = tf.reduce_mean(tf.square(z_e_x - tf.stop_gradient(z_nst_q_x)))
        #rec_loss = tf.reduce_mean(tf.reduce_sum(BernoulliCrossEntropyCost(x_tilde, images), axis=[1, 2]))
        #vq_loss = tf.reduce_mean(tf.reduce_sum(tf.square(tf.stop_gradient(z_e_x) - z_q_x), axis=[1, 2, 3]))
        #commit_loss = tf.reduce_mean(tf.reduce_sum(tf.square(z_e_x - tf.stop_gradient(z_q_x)), axis=[1, 2, 3]))
        beta = 0.25
        loss = rec_loss + vq_loss + beta * commit_loss
        params = get_params_dict()
        grads = tf.gradients(loss, params.values())

        learning_rate = 0.0002
        optimizer = tf.train.AdamOptimizer(learning_rate, use_locking=True)
        assert len(grads) == len(params)
        j = [(g, p) for g, p in zip(grads, params.values())]
        train_step = optimizer.apply_gradients(j)

    things_names = ["images",
                    "bn_flag",
                    "x_tilde_mix",
                    "x_tilde_means",
                    "x_tilde_lin_scales",
                    "x_tilde_coeffs",
                    "z_e_x",
                    "z_q_x",
                    "z_i_x",
                    "z_emb",
                    "loss",
                    "rec_loss",
                    "train_step"]
    things_tf = [eval(name) for name in things_names]
    for tn, tt in zip(things_names, things_tf):
        graph.add_to_collection(tn, tt)
    train_model = namedtuple('Model', things_names)(*things_tf)
    return graph, train_model

g, vs = create_graph()

def loop(sess, itr, extras, stateful_args):
    x, = itr.next_batch()
    if extras["train"]:
        feed = {vs.images: x,
                vs.bn_flag: 0.}
        outs = [vs.rec_loss, vs.loss, vs.train_step]
        r = sess.run(outs, feed_dict=feed)
        l = r[0]
        t_l = r[1]
        step = r[2]
    else:
        feed = {vs.images: x,
                vs.bn_flag: 1.}
        outs = [vs.rec_loss]
        r = sess.run(outs, feed_dict=feed)
        l = r[0]
    return l, None, stateful_args

with tf.Session(graph=g) as sess:
    run_loop(sess,
             loop, train_itr,
             loop, val_itr,
             n_steps=10000,
             n_train_steps_per=1000,
             n_valid_steps_per=1000)
