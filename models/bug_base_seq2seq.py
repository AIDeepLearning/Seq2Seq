import tensorflow as tf
import math
from utils.config import GO, EOS


class Seq2SeqModel():
    def __init__(self, config, mode, logger):
        assert mode.lower() in ['train', 'inference']
        self.mode = mode.lower()
        self.logger = logger
        self.init_config(config)
        self.build_placeholders()
        self.build_embed()
        self.build_encoder()
        self.build_decoder()
        #self.build_optimizer()
    
    def init_config(self, config):
        self.config = config
        self.hidden_units = config['hidden_units']
        self.embedding_size = config['embedding_size']
        self.encoder_max_time_steps = config['decoder_max_time_steps']
        self.decoder_max_time_steps = config['decoder_max_time_steps']
        self.encoder_depth = config['encoder_depth']
        self.decoder_depth = config['decoder_depth']
        self.encoder_vocab_size = config['encoder_vocab_size']
        self.decoder_vocab_size = config['decoder_vocab_size']
        self.logger_name = config['logger_name']
        self.dropout_rate = config['dropout_rate']
        self.dtype = tf.float16 if config['use_fp16'] else tf.float32
        self.optimizer_type = config['optimizer_type']
        self.learning_rate = config['learning_rate']
        self.max_gradient_norm = config['max_gradient_norm']
        self.use_bidirectional = config['use_bidirectional']
        self.use_dropout = config['use_dropout']
        self.batch_size = 5
        self.encoder_max_time_steps = 29
        self.decoder_max_time_steps = 29
        self.global_step = tf.Variable(0, trainable=False, name='global_step')
        self.global_epoch_step = tf.Variable(0, trainable=False, name='global_epoch_step')
        self.global_epoch_step_op = tf.assign(self.global_epoch_step, tf.add(self.global_epoch_step, 1))
    
    def build_placeholders(self):
        
        self.keep_prob = tf.placeholder(self.dtype, shape=[], name='keep_prob')
        
        # encoder_inputs: [batch_size, max_time_steps]
        self.encoder_inputs = tf.placeholder(dtype=tf.int32, shape=[self.batch_size, self.encoder_max_time_steps],
                                             name='encoder_inputs')
        self.logger.debug('encoder_inputs %s', self.encoder_inputs)
        
        # encoder_inputs_length: [batch_size]
        self.encoder_inputs_length = tf.placeholder(dtype=tf.int32, shape=[self.batch_size],
                                                    name='encoder_inputs_length')
        self.logger.debug('encoder_inputs_length %s', self.encoder_inputs_length)
        
        # batch_size
        # self.batch_size = tf.shape(self.encoder_inputs)[0]
        # self.logger.debug('batch_size %s', self.batch_size)
        
        if self.mode == 'train':
            
            # decoder_inputs: [batch_size, max_time_steps]
            self.decoder_inputs = tf.placeholder(dtype=tf.int32, shape=[self.batch_size, self.decoder_max_time_steps],
                                                 name='decoder_inputs')
            self.logger.debug('decoder_inputs %s', self.decoder_inputs)
            
            # decoder_inputs_length: [batch_size]
            self.decoder_inputs_length = tf.placeholder(dtype=tf.int32, shape=[self.batch_size],
                                                        name='decoder_inputs_length')
            self.logger.debug('decoder_inputs_length %s', self.decoder_inputs_length)
            
            # decoder_start_token: [batch_size, 1]
            self.decoder_start_token = tf.ones(shape=[self.batch_size, 1], dtype=tf.int32) * GO
            self.logger.debug('decoder_start_token %s', self.decoder_start_token)
            
            # decoder_end_token: [batch_size, 1]
            self.decoder_end_token = tf.ones(shape=[self.batch_size, 1], dtype=tf.int32) * EOS
            self.logger.debug('decoder_end_token %s', self.decoder_end_token)
            
            # decoder_inputs_train: [batch_size, max_time_steps + 1]
            self.decoder_inputs_train = tf.concat([self.decoder_start_token, self.decoder_inputs], axis=-1)
            self.logger.debug('decoder_inputs_train %s', self.decoder_inputs_train)
            
            # decoder_inputs_train_length: [batch_size]
            self.decoder_inputs_train_length = self.decoder_inputs_length + 1
            self.logger.debug('decoder_inputs_train_length %s', self.decoder_inputs_train_length)
            
            # decoder_targets_train: [batch_size, max_time_steps + 1]
            self.decoder_targets_train = tf.concat([self.decoder_inputs, self.decoder_end_token], axis=-1)
            self.logger.debug('decoder_targets_train %s', self.decoder_targets_train)
            
            # decoder_targets_length: [batch_size]
            self.decoder_targets_train_length = self.decoder_inputs_length + 1
            self.logger.debug('decoder_targets_train_length %s', self.decoder_targets_train_length)
        
        else:
            self.decoder_inputs = tf.ones(shape=[self.batch_size, 1], dtype=tf.int32, name='decoder_inputs') * GO
            self.logger.debug('decoder_inputs %s', self.decoder_inputs)
            
            self.decoder_inputs_inference = self.decoder_inputs
            self.logger.debug('decoder_inputs_inference %s', self.decoder_inputs_inference)
            
            self.decoder_inputs_inference_length = tf.ones(shape=[self.batch_size], dtype=tf.int32,
                                                           name='decoder_inputs_inference_length')
            self.logger.debug('decoder_inputs_inference_length %s', self.decoder_inputs_inference_length)
    
    def build_single_cell(self):
        """
        build single cell, lstm or gru or RNN
        :return: GRUCell or LSTMCell or RNNCell
        """
        cell = tf.nn.rnn_cell.GRUCell(self.hidden_units, name='single_cell')
        if self.use_dropout:
            cell = tf.nn.rnn_cell.DropoutWrapper(cell=cell, dtype=self.dtype, output_keep_prob=self.keep_prob)
        return cell
    
    def build_encoder_cell(self, depth=None):
        """
        build encoder multi cell
        :return: MultiRNNCell
        """
        depth = depth if depth else self.encoder_depth
        cells = [self.build_single_cell() for _ in range(depth)]
        return tf.nn.rnn_cell.MultiRNNCell(cells=cells)

    def create_bi_rnn(self, inputs, scope='bi_rnn', reuse=None):
        with tf.variable_scope(scope, reuse=reuse):
            cell_fw = tf.contrib.rnn.GRUCell(self.hidden_units)
            cell_bw = tf.contrib.rnn.GRUCell(self.hidden_units)
            outputs, states = tf.nn.bidirectional_dynamic_rnn(cell_fw, cell_bw, inputs, dtype=tf.float32)
        return outputs, states

    def build_embed(self):
        import math
        sqrt3 = math.sqrt(3)  # Uniform(-sqrt(3), sqrt(3)) has variance=1.
        initializer = tf.random_uniform_initializer(-sqrt3, sqrt3, dtype=self.dtype)
    
        self.lookup_table = tf.get_variable('lookup_table', dtype=tf.float32,
                                            shape=[self.encoder_vocab_size, self.embedding_size],
                                            initializer=initializer)

    def build_encoder2(self):
        encoder_enc = tf.nn.embedding_lookup(self.lookup_table, self.encoder_inputs)
        outputs_1, states_1 = self.create_bi_rnn(encoder_enc, scope='encoder_birnn_1')
        outputs_1 = tf.concat(outputs_1, -1)
        outputs_2, states_2 = self.create_bi_rnn(outputs_1, scope='encoder_birnn_2')
        forward_state, backward_state = states_2
        self.encoder_last_state = backward_state
        print('encoder_last_state', self.encoder_last_state)
    
    def build_encoder(self):
        with tf.variable_scope('encoder'):
            # encoder_embeddings: [encoder_vocab_size, embedding_size]
            self.encoder_embeddings = tf.get_variable(name='embedding',
                                                      shape=[self.encoder_vocab_size, self.embedding_size],
                                                      dtype=self.dtype,
                                                      initializer=tf.random_uniform_initializer(-math.sqrt(3), math.sqrt(3), dtype=self.dtype))
            self.logger.debug('encoder_embeddings %s', self.encoder_embeddings)
            
            # encoder_inputs_embedded : [batch_size, encoder_max_time_steps, embedding_size]
            self.encoder_inputs_embedded = tf.nn.embedding_lookup(params=self.encoder_embeddings,
                                                                  ids=self.encoder_inputs,
                                                                  name='inputs_embedded')
            self.logger.debug('encoder_inputs_embedded %s', self.encoder_inputs_embedded)
            
            # encoder_inputs_embedded_dense: [batch_size, encoder_max_time_steps, hidden_units]
            self.encoder_inputs_embedded_dense = tf.layers.dense(inputs=self.encoder_inputs_embedded,
                                                                 units=self.hidden_units,
                                                                 use_bias=False,
                                                                 name='inputs_embedded_dense')
            self.logger.debug('encoder_inputs_embedded_dense %s', self.encoder_inputs_embedded_dense)
            
            if self.use_bidirectional:
                # cell forward
                cell_fw = self.build_single_cell()
                # cell backward
                cell_bw = self.build_single_cell()
                
                bi_outputs, bi_last_state = tf.nn.bidirectional_dynamic_rnn(cell_fw=cell_fw,
                                                                            cell_bw=cell_bw,
                                                                            inputs=self.encoder_inputs_embedded_dense,
                                                                            sequence_length=self.encoder_inputs_length,
                                                                            dtype=self.dtype)
                self.logger.debug('bi_outputs %s', bi_outputs)
                self.logger.debug('bi_last_state %s', bi_last_state)
                # concat bi outputs
                bi_outputs = tf.layers.dense(inputs=tf.concat(bi_outputs, axis=-1), units=self.hidden_units,
                                             use_bias=False)
                self.logger.debug('bi_outputs %s', bi_outputs)
                
                if self.encoder_depth > 2:
                    upper_cell = self.build_encoder_cell(self.encoder_depth - 1)
                elif self.encoder_depth == 2:
                    upper_cell = self.build_single_cell()
                else:
                    upper_cell = None
                
                self.logger.debug('upper_cell %s', upper_cell)
                
                if upper_cell:
                    # encoder depth >= 2
                    upper_outputs, upper_last_state = tf.nn.dynamic_rnn(cell=upper_cell, inputs=bi_outputs,
                                                                        sequence_length=self.encoder_inputs_length,
                                                                        dtype=self.dtype)
                    self.logger.debug('upper_outputs %s', upper_outputs)
                    self.logger.debug('upper_last_state %s', upper_last_state)
                    
                    # encoder_outputs: [batch_size, encoder_max_time_steps, hidden_units]
                    self.encoder_outputs = upper_outputs
                    self.logger.debug('encoder_outputs %s', self.encoder_outputs)
                    
                    # encoder_last_state: [batch_size, hidden_units] * encoder_depth
                    self.encoder_last_state = (bi_last_state[0],) + (
                        (upper_last_state,) if self.encoder_depth == 2 else upper_last_state)
                    self.logger.debug('encoder_last_state %s', self.encoder_last_state)
                else:
                    # encoder_outputs: [batch_size, encoder_max_time_steps, hidden_units]
                    self.encoder_outputs = bi_outputs
                    self.logger.debug('encoder_outputs %s', self.encoder_outputs)
                    
                    # encoder_last_state: [batch_size, hidden_units] * encoder_depth
                    self.encoder_last_state = (bi_last_state[0],)
                    self.logger.debug('encoder_last_state %s', self.encoder_last_state)
            
            else:
                # encoder_cell
                self.encoder_cell = self.build_encoder_cell()
                self.logger.debug('encoder_cell %s', self.encoder_cell)
                # encoder_outputs: [batch_size, encoder_max_time_steps, hidden_units]
                # encoder_last_state: [batch_size, hidden_units] * encoder_depth
                self.encoder_outputs, self.encoder_last_state = tf.nn.dynamic_rnn(cell=self.encoder_cell,
                                                                                  inputs=self.encoder_inputs_embedded_dense,
                                                                                  sequence_length=self.encoder_inputs_length,
                                                                                  dtype=self.dtype)
                self.logger.debug('encoder_outputs %s', self.encoder_outputs)
                self.logger.debug('encoder_last_state %s', self.encoder_last_state)
    
    def build_decoder_cell(self, depth=None):
        depth = depth if depth else self.decoder_depth
        cells = [self.build_single_cell() for _ in range(depth)]
        return tf.nn.rnn_cell.MultiRNNCell(cells=cells)

    def build_decoder(self):
        self.max_sequence_length = tf.reduce_max(self.decoder_targets_train_length, name='max_length')
        self.mask = tf.sequence_mask(self.decoder_inputs_train_length, self.max_sequence_length, dtype=tf.float32,
                                     name='masks')
        decoder_enc = tf.nn.embedding_lookup(self.lookup_table, self.decoder_inputs_train)
        # decoder_cell = tf.contrib.rnn.GRUCell(self.hidden_units)
        decoder_cell = self.build_decoder_cell()
        
        self.initial_state = self.encoder_last_state
        logits, states = tf.nn.dynamic_rnn(decoder_cell, decoder_enc,
                                           initial_state=self.initial_state,
                                           sequence_length=self.decoder_inputs_train_length, dtype=tf.float32)
        self.last_state = states
        self.outputs = tf.layers.dense(logits, self.encoder_vocab_size, use_bias=True)
        self.probs = tf.nn.softmax(self.outputs, -1)
        self.decoder_predicts = tf.argmax(self.probs, -1)
    
        # training settings
        if self.mode == 'train':
            self.loss = tf.contrib.seq2seq.sequence_loss(logits=self.outputs,
                                                         targets=self.decoder_targets_train, weights=self.mask)
        
            print('lloss', self.loss)
            optimizer = tf.train.AdamOptimizer(self.learning_rate)
            trainable_params = tf.trainable_variables()
            gradients = tf.gradients(self.loss, trainable_params)
            clip_gradients, _ = tf.clip_by_global_norm(gradients, 5.0)
            self.global_step = tf.Variable(0, name='global_step', trainable=False)
        
            self.train_op = optimizer.apply_gradients(zip(clip_gradients, trainable_params),
                                                      global_step=self.global_step)
            print('train op', self.train_op)

    def build_decoder3(self):
        with tf.variable_scope('decoder'):
            # decoder_initial_state: [batch_size, hidden_units]
            self.decoder_initial_state = self.encoder_last_state
            self.logger.debug('decoder_initial_state %s', self.decoder_initial_state)
            
            #self.decoder_cell = self.build_decoder_cell()
            self.decoder_cell = tf.contrib.rnn.LSTMCell(self.hidden_units)

            self.logger.debug('decoder_cell %s', self.decoder_cell)
            
            # decoder_embeddings: [decoder_vocab_size, embedding_size]
            self.decoder_embeddings = tf.get_variable(name='embedding',
                                                      shape=[self.decoder_vocab_size, self.embedding_size],
                                                      dtype=self.dtype,
                                                      initializer=tf.random_uniform_initializer(-math.sqrt(3), math.sqrt(3), dtype=self.dtype))
            self.logger.debug('decoder_embeddings %s', self.decoder_embeddings)
            
            # decoder_inputs_embedded: [batch_size, decoder_max_time_steps, embedding_size]
            self.decoder_inputs_embedded = tf.nn.embedding_lookup(params=self.decoder_embeddings,
                                                                  ids=self.decoder_inputs_train)
            self.logger.debug('decoder_inputs_embedded %s', self.decoder_inputs_embedded)
            
            # decoder_outputs: [batch_size, decoder_max_time_steps, hidden_units]
            # decoder_last_state: [batch_size, hidden_units]
            self.decoder_outputs, self.decoder_last_state = tf.nn.dynamic_rnn(cell=self.decoder_cell,
                                                                              inputs=self.decoder_inputs_embedded,
                                                                              sequence_length=self.decoder_inputs_train_length,
                                                                              dtype=self.dtype)
            
            
            
            self.logger.debug('decoder_outputs %s', self.decoder_outputs)
            self.logger.debug('decoder_last_state %s', self.decoder_last_state)
            
            # decoder_logits: [batch_size, decoder_max_time_steps, decoder_vocab_size]
            self.decoder_logits = tf.layers.dense(inputs=self.decoder_outputs,
                                                  units=self.decoder_vocab_size,
                                                  name='decoder_logits')
            self.logger.debug('decoder_logits %s', self.decoder_logits)
            
            if self.mode == 'train':
                # decoder_masks: [batch_size, reduce_max(decoder_inputs_length)]
                self.decoder_masks = tf.sequence_mask(lengths=self.decoder_inputs_train_length,
                                                      maxlen=tf.reduce_max(self.decoder_targets_train_length),
                                                      dtype=self.dtype,
                                                      name='masks')
                self.logger.debug('decoder_masks %s', self.decoder_masks)
                
                # loss
                self.loss = tf.contrib.seq2seq.sequence_loss(logits=self.decoder_logits,
                                                             targets=self.decoder_targets_train,
                                                             weights=self.decoder_masks)
                self.logger.debug('loss %s', self.loss)
            
            #else:
                # decoder_probabilities: [batch_size, decoder_max_time_steps, decoder_vocab_size]
                self.decoder_probabilities = tf.nn.softmax(self.decoder_logits, -1)
                self.logger.debug('decoder_probabilities %s', self.decoder_probabilities)
                
                # decoder_predicts: [batch_size, decoder_max_time_steps]
                self.decoder_predicts = tf.argmax(self.decoder_probabilities, -1)
                self.logger.debug('decoder_predicts %s', self.decoder_predicts)
        self.build_optimizer()
        
    def build_optimizer(self):
        if self.mode == 'train':
            self.logger.info('Setting optimizer...')
            
            # trainable_verbs
            self.trainable_verbs = tf.trainable_variables()
            # self.logger.debug('trainable_verbs %s', self.trainable_verbs)
            
            if self.optimizer_type.lower() == 'adam':
                self.optimizer = tf.train.AdadeltaOptimizer(learning_rate=self.learning_rate)
                self.logger.info('Optimizer has been set')
            
            # compute gradients
            self.gradients = tf.gradients(ys=self.loss, xs=self.trainable_verbs)
            
            # clip gradients by a given maximum_gradient_norm
            self.clip_gradients, _ = tf.clip_by_global_norm(self.gradients, self.max_gradient_norm)
            
            # train op
            self.train_op = self.optimizer.apply_gradients(zip(self.clip_gradients, self.trainable_verbs),
                                                          global_step=self.global_step)
            
            # self.train_op = self.optimizer.minimize(loss=self.loss, global_step=self.global_step)
    
    def save(self, sess, save_path, var_list=None, global_step=None):
        saver = tf.train.Saver(var_list)
        
        # save model
        saver.save(sess=sess, save_path=save_path, global_step=global_step)
        self.logger.info('model saved at %s', save_path)
    
    def restore(self, sess, save_path, var_list=None):
        saver = tf.train.Saver(var_list)
        saver.restore(sess=sess, save_path=save_path)
        self.logger.info('model restored from %s', save_path)
    
    def train(self, sess, encoder_inputs, encoder_inputs_length,
              decoder_inputs, decoder_inputs_length):
        
        input_feed = {
            self.encoder_inputs.name: encoder_inputs,
            self.encoder_inputs_length.name: encoder_inputs_length,
            self.decoder_inputs.name: decoder_inputs,
            self.decoder_inputs_length.name: decoder_inputs_length,
            self.keep_prob.name: 1 - self.dropout_rate
        }
        
        output_feed = [
            self.loss,
            self.train_op,
            self.decoder_predicts,
            self.decoder_targets_train
        ]
        outputs = sess.run(fetches=output_feed, feed_dict=input_feed)
        return outputs
    
    def eval(self, sess, encoder_inputs, encoder_inputs_length,
             decoder_inputs, decoder_inputs_length):
        
        input_feed = {
            self.encoder_inputs.name: encoder_inputs,
            self.encoder_inputs_length.name: encoder_inputs_length,
            self.decoder_inputs.name: decoder_inputs,
            self.decoder_inputs_length.name: decoder_inputs_length,
            self.keep_prob.name: 1
        }
        
        output_feed = self.loss
        
        outputs = sess.run(fetches=output_feed, feed_dict=input_feed)
        return outputs
    
    def inference(self, sess, encoder_inputs, encoder_inputs_length):
        input_feed = {
            self.encoder_inputs.name: encoder_inputs,
            self.encoder_inputs_length.name: encoder_inputs_length,
            self.keep_prob.name: 1
        }
        
        output_feed = [
            self.decoder_probabilities,
            self.decoder_predicts,
        ]
        outputs = sess.run(fetches=output_feed, feed_dict=input_feed)
        return outputs
