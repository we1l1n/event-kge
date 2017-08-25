import tensorflow as tf
import numpy as np
from models.model import dot_similarity, dot, max_margin, skipgram_loss, lstm_loss, concat_window_loss, rnn_loss, trans, ident_entity


class TEKE(object):
    def __init__(self, num_entities, num_relations, embedding_size, batch_size_kg, fnsim, init_lr=1.0, alpha=1.0):
        """
        Implements translation-based triplet scoring from negative sampling (TransE)
        :param num_entities:
        :param num_relations:
        :param embedding_size:
        :param batch_size_kg:
        :param batch_size_sg:
        :param num_sampled:
        :param vocab_size:
        :param leftop:
        :param rightop:
        :param fnsim:
        """
        self.num_entities = num_entities
        self.num_relations = num_relations
        self.embedding_size = embedding_size
        self.batch_size_kg = batch_size_kg

        self.leftop = trans
        self.rightop = ident_entity
        self.fnsim = fnsim
        self.init_lr = init_lr
        self.alpha = alpha

    def rank_left_idx(self, test_inpr, test_inpo, r_embs, ent_embs, A, n_h, n_t):
        # every unique combination of inpr inpo
        results = np.zeros((len(test_inpr), ent_embs.shape[0]))

        lhs = n_h.dot(A) + ent_embs
        unique_inpo = np.unique(test_inpo)
        unique_rell = r_embs[unique_inpo]
        rhs = n_t.dot(A) + ent_embs[test_inpr]
        unique_lhs = lhs[:, np.newaxis] + unique_rell

        for r, i in enumerate(unique_inpo):
            rhs_inds = np.argwhere(test_inpo == i)[:,0]
            tmp_lhs = unique_lhs[:, r, :]
            results[rhs_inds] = -np.square(tmp_lhs[:, np.newaxis] - rhs[rhs_inds]).sum(axis=2).transpose()
        return results

    def rank_right_idx(self, test_inpl, test_inpo, r_embs, ent_embs, A, n_h, n_t):
        rhs = n_t.dot(A) + ent_embs
        unique_inpo = np.unique(test_inpo)
        unique_rell = r_embs[unique_inpo]
        unique_rhs = unique_rell - rhs[:, np.newaxis]
        lhs = n_h.dot(A) + ent_embs[test_inpl]  # [num_test, d]
        results = np.zeros((len(test_inpl), ent_embs.shape[0]))
        for r, i in enumerate(unique_inpo):
            lhs_inds = np.argwhere(test_inpo == i)[:, 0]
            tmp_rhs = unique_rhs[:, r, :]
            results[lhs_inds] = -np.square(lhs[lhs_inds] + tmp_rhs[:,np.newaxis]).sum(axis=2).transpose()
        return results

    def create_graph(self):
        print('Building Model')
        # Translation Model initialisation
        w_bound = np.sqrt(6. / self.embedding_size)
        self.E = tf.Variable(tf.random_uniform((self.num_entities, self.embedding_size), minval=-w_bound,
                                               maxval=w_bound), name="E")
        self.R = tf.Variable(tf.random_uniform((self.num_relations, self.embedding_size), minval=-w_bound,
                                               maxval=w_bound), name="R")

        self.A = tf.Variable(tf.random_uniform((self.embedding_size, self.embedding_size), minval=-w_bound,
                                               maxval=w_bound), name="A")

        self.n_x_h = tf.placeholder(tf.float32, [self.batch_size_kg, self.embedding_size])
        self.n_x_t = tf.placeholder(tf.float32, [self.batch_size_kg, self.embedding_size])

        self.n_x_hn = tf.placeholder(tf.float32, [self.batch_size_kg, self.embedding_size])
        self.n_x_tn = tf.placeholder(tf.float32, [self.batch_size_kg, self.embedding_size])

        self.normalize_E = self.E.assign(tf.nn.l2_normalize(self.E, 1))
        self.normalize_R = self.R.assign(tf.nn.l2_normalize(self.R, 1))

        self.inpr = tf.placeholder(tf.int32, [self.batch_size_kg], name="rhs")
        self.inpl = tf.placeholder(tf.int32, [self.batch_size_kg], name="lhs")
        self.inpo = tf.placeholder(tf.int32, [self.batch_size_kg], name="rell")

        self.inprn = tf.placeholder(tf.int32, [self.batch_size_kg], name="rhsn")
        self.inpln = tf.placeholder(tf.int32, [self.batch_size_kg], name="lhsn")
        self.inpon = tf.placeholder(tf.int32, [self.batch_size_kg], name="relln")

        lhs = tf.nn.embedding_lookup(self.E, self.inpl)
        rhs = tf.nn.embedding_lookup(self.E, self.inpr)
        rell = tf.nn.embedding_lookup(self.R, self.inpo)

        lhsn = tf.nn.embedding_lookup(self.E, self.inpln)
        rhsn = tf.nn.embedding_lookup(self.E, self.inprn)
        relln = tf.nn.embedding_lookup(self.R, self.inpon)

        lhs = tf.matmul(self.n_x_h, self.A) + lhs
        rhs = tf.matmul(self.n_x_t, self.A) + rhs
        # rell = tf.matmul(self.n_x_y, self.B) + rell

        lhsn = tf.matmul(self.n_x_hn, self.A) + lhsn
        rhsn = tf.matmul(self.n_x_tn, self.A) + rhsn
        # relln = tf.matmul(self.n_x_yn, self.B) + relln

        # dummy not used
        self.train_inputs = tf.placeholder(tf.int32, shape=[None])
        self.train_labels = tf.placeholder(tf.int32, shape=[None, 1])

        if self.fnsim == dot_similarity:
            simi = tf.diag_part(self.fnsim(self.leftop(lhs, rell), tf.transpose(self.rightop(rhs, rell)),
                                           broadcast=False))
            simin = tf.diag_part(self.fnsim(self.leftop(lhsn, rell), tf.transpose(self.rightop(rhsn, rell)),
                                            broadcast=False))
        else:
            simi = self.fnsim(self.leftop(lhs, rell), self.rightop(rhs, rell), broadcast=False)
            simin = self.fnsim(self.leftop(lhsn, relln), self.rightop(rhsn, relln), broadcast=False)

        kg_loss = max_margin(simi, simin)

        self.reg1 = tf.maximum(0., tf.reduce_sum(tf.sqrt(tf.reduce_sum(tf.matmul(self.n_x_h, self.A)**2, axis=1)) - 1))
        self.reg2 = tf.maximum(0., tf.reduce_sum(tf.sqrt(tf.reduce_sum(tf.matmul(self.n_x_t, self.A) ** 2, axis=1)) - 1))
        #reg2_z = dot(self.W, self.R) ** 2
        #reg2_n = tf.expand_dims(tf.sqrt(tf.reduce_sum(self.R ** 2, axis=1)), 1)
        #reg2 = tf.reduce_sum(tf.maximum(0., (reg2_z / reg2_n) - epsilon))

        self.loss = kg_loss

        self.global_step = tf.Variable(0, trainable=False)
        starter_learning_rate = self.init_lr

        learning_rate = tf.constant(starter_learning_rate)
        self.optimizer = tf.train.AdagradOptimizer(learning_rate).minimize(self.loss)

    def assign_initial(self, init_embeddings):
        return self.E.assign(init_embeddings)

    def post_ops(self):
        return [self.normalize_E, self.normalize_R]

    def train(self):
        return [self.optimizer, self.loss]

    def variables(self):
        return [self.E, self.R, self.A]