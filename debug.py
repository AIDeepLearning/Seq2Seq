import tensorflow as tf
import tensorflow.contrib.eager as tfe

from models import DebugPointerGeneratorCoverageModel, DebugPointerGeneratorModel
from utils.funcs import prepare_pair_batch

tfe.enable_eager_execution()
import logging

# Data loading parameters

tf.app.flags.DEFINE_string('source_vocabulary', 'dataset/lcsts/word/vocabs.json', 'Path to source vocabulary')
tf.app.flags.DEFINE_string('target_vocabulary', 'dataset/lcsts/word/vocabs.json', 'Path to target vocabulary')
tf.app.flags.DEFINE_string('source_train_data', 'dataset/lcsts/word/sources.eval.txt',
                           'Path to source training data')
tf.app.flags.DEFINE_string('target_train_data', 'dataset/lcsts/word/summaries.eval.txt',
                           'Path to target training data')
tf.app.flags.DEFINE_string('source_valid_data', 'dataset/lcsts/word/valid.x.txt',
                           'Path to source validation data')
tf.app.flags.DEFINE_string('target_valid_data', 'dataset/lcsts/word/valid.y.txt',
                           'Path to target validation data')

# Network parameters
tf.app.flags.DEFINE_string('cell_type', 'gru', 'RNN cell for encoder and decoder, default: lstm')
tf.app.flags.DEFINE_string('attention_type', 'bahdanau', 'Attention mechanism: (bahdanau, luong), default: bahdanau')
tf.app.flags.DEFINE_integer('hidden_units', 500, 'Number of hidden units in each layer')
tf.app.flags.DEFINE_integer('attention_units', 256, 'Number of attention units in each layer')
tf.app.flags.DEFINE_integer('encoder_depth', 3, 'Number of layers in encoder')
tf.app.flags.DEFINE_integer('decoder_depth', 3, 'Number of layers in decoder')
tf.app.flags.DEFINE_integer('embedding_size', 300, 'Embedding dimensions of encoder and decoder inputs')
tf.app.flags.DEFINE_integer('encoder_vocab_size', 30000, 'Source vocabulary size')
tf.app.flags.DEFINE_integer('decoder_vocab_size', 30000, 'Target vocabulary size')
tf.app.flags.DEFINE_boolean('use_residual', False, 'Use residual connection between layers')
tf.app.flags.DEFINE_boolean('use_dropout', True, 'Use dropout in each rnn cell')
tf.app.flags.DEFINE_boolean('use_bidirectional', False, 'Use bidirectional rnn cell')
tf.app.flags.DEFINE_float('dropout_rate', 0.3, 'Dropout probability for input/output/state units (0.0: no dropout)')
tf.app.flags.DEFINE_string('split_sign', ' ', 'Separator of dataset')

# Training parameters
tf.app.flags.DEFINE_float('learning_rate', 0.0002, 'Learning rate')
tf.app.flags.DEFINE_float('max_gradient_norm', 1.0, 'Clip gradients to this norm')
tf.app.flags.DEFINE_integer('batch_size', 5, 'Batch size')
tf.app.flags.DEFINE_integer('max_epochs', 10000, 'Maximum # of training epochs')
tf.app.flags.DEFINE_integer('max_load_batches', 20, 'Maximum # of batches to load at one time')
tf.app.flags.DEFINE_integer('encoder_max_time_steps', 30, 'Maximum sequence length')
tf.app.flags.DEFINE_integer('decoder_max_time_steps', 30, 'Maximum sequence length')
tf.app.flags.DEFINE_float('coverage_loss_weight', 1.0, 'Coverage loss weight')
tf.app.flags.DEFINE_integer('display_freq', 5, 'Display training status every this iteration')
tf.app.flags.DEFINE_integer('save_freq', 1000, 'Save model checkpoint every this iteration')
tf.app.flags.DEFINE_integer('valid_freq', 200, 'Evaluate model every this iteration: valid_data needed')
tf.app.flags.DEFINE_string('optimizer_type', 'adam', 'Optimizer for training: (adadelta, adam, rmsprop)')
tf.app.flags.DEFINE_string('model_dir', 'checkpoints/couplet', 'Path to save model checkpoints')
tf.app.flags.DEFINE_string('model_name', 'model.ckpt', 'File name used for model checkpoints')
tf.app.flags.DEFINE_boolean('use_fp16', False, 'Use half precision float16 instead of float32 as dtype')
tf.app.flags.DEFINE_boolean('shuffle_each_epoch', False, 'Shuffle training dataset for each epoch')
tf.app.flags.DEFINE_boolean('sort_by_length', False, 'Sort pre-fetched mini batches by their target sequence lengths')

# Runtime parameters
tf.app.flags.DEFINE_string('gpu', '-1', 'GPU number')
tf.app.flags.DEFINE_boolean('allow_soft_placement', True, 'Allow device soft placement')
tf.app.flags.DEFINE_boolean('log_device_placement', False, 'Log placement of ops on devices')
tf.app.flags.DEFINE_boolean('debug', True, 'Enable debug mode')
tf.app.flags.DEFINE_string('logger_name', 'train', 'Logger name')
tf.app.flags.DEFINE_string('logger_format', '%(asctime)s - %(name)s - %(levelname)s - %(message)s', 'Logger format')
tf.app.flags.DEFINE_integer('beam_width', 1, 'Beam width used in beam search')
tf.app.flags.DEFINE_integer('inference_batch_size', 256, 'Batch size used for decoding')
tf.app.flags.DEFINE_integer('max_inference_step', 60, 'Maximum time step limit to decode')
tf.app.flags.DEFINE_string('model_path', 'checkpoints/couplet_seq2seq/couplet.ckpt-70000',
                           'Path to a specific model checkpoint.')
tf.app.flags.DEFINE_string('inference_input', 'dataset/couplet/test.x.txt', 'Decoding input path')
tf.app.flags.DEFINE_string('inference_output', 'dataset/couplet/test.inference.txt', 'Decoding output path')

# Runtime parameters

FLAGS = tf.app.flags.FLAGS

logging_level = logging.DEBUG if FLAGS.debug else logging.INFO
logging.basicConfig(level=logging_level, format=FLAGS.logger_format)
logger = logging.getLogger(FLAGS.logger_name)

handler = logging.FileHandler('debug.log')
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

config = FLAGS.flag_values_dict()

mode = 'inference'

train_set = TextIterator(source=FLAGS.source_train_data,
                               target=FLAGS.target_train_data,
                               source_dict=FLAGS.source_vocabulary,
                               target_dict=FLAGS.target_vocabulary,
                               batch_size=FLAGS.batch_size,
                               n_words_source=FLAGS.encoder_vocab_size,
                               n_words_target=FLAGS.decoder_vocab_size,
                               sort_by_length=FLAGS.sort_by_length,
                               split_sign=FLAGS.split_sign,
                               max_length=None,
                               )

train_set.reset()
# source_batch, target_batch, source_extend_batch, target_extend_batch, oovs_max_size = [], [], [], [], None

for batch in train_set.next():
    source_batch, target_batch, source_extend_batch, target_extend_batch, oovs_max_size, oovs_vocabs = batch
    print(oovs_vocabs)
    # break

# print(source_extend_batch)
    
    source, source_len, target, target_len = prepare_pair_batch(
        source_batch, target_batch,
        FLAGS.encoder_max_time_steps,
        FLAGS.decoder_max_time_steps)
    
    # Get a batch from training parallel data
    source_extend, _, target_extend, _ = prepare_pair_batch(
        source_extend_batch, target_extend_batch,
        FLAGS.encoder_max_time_steps,
        FLAGS.decoder_max_time_steps)

# print()
#
# data = {
#     'encoder_inputs': source,
#     'encoder_inputs_length': source_len,
#     'encoder_inputs_extend': source_extend,
#     'decoder_inputs': target,
#     'decoder_inputs_extend': target_extend,
#     'decoder_inputs_length': target_len,
#     # 'oovs_max_size': oovs_max_size,
#     # 'oovs_vocabs': oovs_vocabs
# }

    print(target_extend)

# model = DebugPointerGeneratorModel(mode=mode, config=config, logger=logger, data=data)


# predicts, scores = model.inference(sess, source, source_len)
