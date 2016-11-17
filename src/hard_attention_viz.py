# -*- coding: utf-8 -*-
"""visualization of the attention weights for inflection generation.

Usage:
  attention_viz.py [--cnn-mem MEM][--input=INPUT] [--hidden=HIDDEN] [--feat-input=FEAT] [--epochs=EPOCHS]
  [--layers=LAYERS] [--optimization=OPTIMIZATION] [--reg=REGULARIZATION] [--learning=LEARNING] [--plot] [--override]
  TRAIN_PATH DEV_PATH TEST_PATH RESULTS_PATH SIGMORPHON_PATH...

Arguments:
  TRAIN_PATH    train set path path
  DEV_PATH      development set path
  TEST_PATH     test set path
  RESULTS_PATH  results file path
  SIGMORPHON_PATH   sigmorphon root containing data, src dirs

Options:
  -h --help                     show this help message and exit
  --cnn-mem MEM                 allocates MEM bytes for (py)cnn
  --input=INPUT                 input vector dimensions
  --hidden=HIDDEN               hidden layer dimensions
  --feat-input=FEAT             feature input vector dimension
  --epochs=EPOCHS               amount of training epochs
  --layers=LAYERS               amount of layers in lstm network
  --optimization=OPTIMIZATION   chosen optimization method ADAM/SGD/ADAGRAD/MOMENTUM/ADADELTA
  --reg=REGULARIZATION          regularization parameter for optimization
  --learning=LEARNING           learning rate parameter for optimization
  --plot                        draw a learning curve plot while training each model
  --override                    override the existing model with the same name, if exists
"""

import numpy as np
import prepare_sigmorphon_data
import datetime
import time
import common
import pycnn as pc
import hard_attention
from sklearn.decomposition import TruncatedSVD

from collections import defaultdict
from multiprocessing import Pool
from matplotlib import pyplot as plt
from docopt import docopt

# default values
INPUT_DIM = 300
FEAT_INPUT_DIM = 100
HIDDEN_DIM = 100
EPOCHS = 1
LAYERS = 2
MAX_PREDICTION_LEN = 50
OPTIMIZATION = 'ADAM'
EARLY_STOPPING = True
MAX_PATIENCE = 100
REGULARIZATION = 0.0
LEARNING_RATE = 0.0001  # 0.1
PARALLELIZE = True
BEAM_WIDTH = 5

NULL = '%'
UNK = '#'
EPSILON = '*'
BEGIN_WORD = '<'
END_WORD = '>'
UNK_FEAT = '@'
STEP = '^'
ALIGN_SYMBOL = '~'


def main(train_path, dev_path, test_path, results_file_path, sigmorphon_root_dir, input_dim, hidden_dim, feat_input_dim,
         epochs, layers, optimization, regularization, learning_rate, plot, override):
    hyper_params = {'INPUT_DIM': input_dim, 'HIDDEN_DIM': hidden_dim, 'FEAT_INPUT_DIM': feat_input_dim,
                    'EPOCHS': epochs, 'LAYERS': layers, 'MAX_PREDICTION_LEN': MAX_PREDICTION_LEN,
                    'OPTIMIZATION': optimization, 'PATIENCE': MAX_PATIENCE, 'REGULARIZATION': regularization,
                    'LEARNING_RATE': learning_rate}

    (alphabet_index, decoder_rnn, encoder_frnn, encoder_rrnn, feat_index, feature_types, initial_model,
     inverse_alphabet_index, dev_words, dev_lemmas, dev_feat_dicts) = init_model(dev_path, feat_input_dim, hidden_dim,
                                                                                 input_dim, layers, results_file_path,
                                                                                 test_path, train_path)

    char_lookup = initial_model["char_lookup"]
    feat_lookup = initial_model["feat_lookup"]

    # "what is learned by the encoder" experiment:
    # get lots of input words (dev set)
    # run blstm encoder on them (encode feats and chars)
    # experiments:
    # we want to understand what's captured/whats more significant: current symbol, context or all?
    # to do so:
    # take the blstm rep. for the same character, same context, different positions. how will it cluster by position?
    # i.e: abbbbbb, babbbb, bbabbbb, bbbabbbb, bbbbabb, bbbbbba...

    # take the blstm rep. for the same character, same position, diff. contexts. how will it cluster by context?
    # aaaabaaaa, bbbbbbbbb, cccbcccc, dddbdddd, eeeebeeee...

    # take the blstm rep. for diff characters, same position, same contexts. how will it cluster by character?
    # aaaaaaaa, aaabaaa, aaacaaa, aaadaaa, aaaeaaa, aaafaaa...

    # other option: take (all?) "natural" (dev) examples, throw on SVD, paint by location, character, context (last one
    #  is more complex but can probably think about something)

    start = 0
    end = len(dev_lemmas) - 1
    encoded_vecs = {}
    encoded_feat_vecs = {}

    index_to_feats_and_lemma = {}

    # get bilstm encoder representation
    for lemma, feats in zip(dev_lemmas[start:end], dev_feat_dicts[start:end]):
        index = common.get_morph_string(feats, feature_types) + lemma
        index_to_feats_and_lemma[index] = (feats, lemma)
        blstm_outputs, feat_vecs = hard_attention.encode_feats_and_chars(alphabet_index, char_lookup,
                                                                         encoder_frnn, encoder_rrnn,
                                                                         feat_index, feat_lookup, feats,
                                                                         feature_types, lemma)
        encoded_vecs[index] = blstm_outputs
        encoded_feat_vecs[index] = feat_vecs

    # get examples (encoder hidden states) by location: 1, 2, 3, 4, 5...
    location_to_vec = {}
    for encoded_rep_index in encoded_vecs:
        encoded_rep = encoded_vecs[encoded_rep_index]
        for location, vec in enumerate(encoded_rep):
            if location in location_to_vec:
                location_to_vec[location].append(vec)
            else:
                location_to_vec[location] = [vec]

    location_labels = []
    vecs = []

    # take 10 samples from each character
    for key in location_to_vec:
        for value in location_to_vec[key][0:100]:
            location_labels.append(key)
            vecs.append(value.vec_value())

    # plot_svd_reduction(hidden_states, location_labels, title='SVD for encoder hidden states by location')

    # get examples (encoder hidden states) by character: א,ב,ג,ד,ה,ו...
    char_to_vec = {}
    char_vecs = []
    char_labels = []
    current_char_lables = []
    char_location_labels = []
    feat_vecs = []
    feat_labels = []
    for encoded_rep_index in encoded_vecs:

        # get bilstm encoding for the sequence
        encoded_rep = encoded_vecs[encoded_rep_index]

        # should skip the feat vecs (?)
        # get matching lemma and features
        feats, lemma = index_to_feats_and_lemma[encoded_rep_index]
        sorted_feats = []
        for feat in sorted(feature_types):
            if feat in feats:
                sorted_feats.append(u'{}:{}'.format(feat, feats[feat]))

        # seq_symbols = ['<'] + list(sorted_feats) + list(lemma) + ['>']
        seq_symbols = ['<'] + list(lemma) + ['>']

        # sort vectors by symbol
        for i, symbol in enumerate(seq_symbols):
            if symbol in lemma:
                char_vecs.append(encoded_rep[i])
                if i > 0:
                    prev_symbol = seq_symbols[i - 1]
                else:
                    prev_symbol = '_'
                if i < len(seq_symbols) - 1:
                    next_symbol = seq_symbols[i + 1]
                else:
                    next_symbol = '_'
                char_labels.append(u'{} ({},{},{})'.format(symbol, prev_symbol, i, next_symbol))
                char_location_labels.append(u'{}'.format(i))
                current_char_lables.append(u'{}'.format(symbol))
            else:
                if symbol in sorted_feats:
                    feat_vecs.append(encoded_rep[i])
                    feat_labels.append(symbol)

            if symbol in char_to_vec:
                char_to_vec[symbol].append(encoded_rep[i])
            else:
                char_to_vec[symbol] = [encoded_rep[i]]

    symbol_labels = []
    vecs = []

    # take 20 samples from each symbol
    for key in char_to_vec:
        for value in char_to_vec[key][0:20]:
            symbol_labels.append(key)
            vecs.append(value.vec_value())

    # plot_svd_reduction(all_hidden_states, symbol_labels, title='SVD for encoder hidden states by symbol')

    char_hidden_states = np.array([v.vec_value() for v in char_vecs])
    # plot_svd_reduction(char_hidden_states[0:100], char_labels[0:100], title='SVD for encoder hidden states by symbol
    # (characters only)')

    plot_svd_reduction(char_hidden_states[0:200], char_labels[0:200], color_labels=char_location_labels[0:200],
                       title='Hard Attention - Encoded Inputs by Location')

    plot_svd_reduction(char_hidden_states[0:500], current_char_lables[0:500], color_labels=char_location_labels[0:500],
                       title='Hard Attention - Encoded Inputs by Location')

    plot_svd_reduction(char_hidden_states[0:500], current_char_lables[0:500], color_labels=current_char_lables[0:500],
                       title='Hard Attention - Encoded Inputs by Character')


    # TODO: get examples (encoder hidden states) by context: after/before א,ב,ג,ד,ה...
    char_embeddings = {}
    char_embeddings_matrix = []
    clean_alphabet_index = {}

    # print SVD for char embeddings
    # workaround to remove feat embeddings from plot
    for char in alphabet_index:
        if not len(char) > 1 and not char.isdigit() and char not in [UNK, UNK_FEAT, EPSILON, NULL]:
            clean_alphabet_index[char] = alphabet_index[char]

    for char in clean_alphabet_index:
        char_embeddings[char] = char_lookup[clean_alphabet_index[char]].vec_value()
        char_embeddings_matrix.append(char_lookup[clean_alphabet_index[char]].vec_value())
    X = np.array(char_embeddings_matrix)

    plot_svd_reduction(X, clean_alphabet_index, title='SVD for character embeddings')

    # print SVD for feat embeddings
    feat_embeddings = {}
    feat_embeddings_matrix = []
    feat_color_labels = []
    for feat in feat_index:
        feat_embeddings[feat] = feat_lookup[feat_index[feat]].vec_value()
        feat_embeddings_matrix.append(feat_lookup[feat_index[feat]].vec_value())
        feat_color_labels.append(feat[:3])
    Y = np.array(feat_embeddings_matrix)

    plot_svd_reduction(Y, feat_index, color_labels=feat_color_labels, title='SVD for feature embeddings')

    return

    print 'Bye!'


def is_number(s):
    try:
        float(s)
        return True
    except ValueError:
        return False


def plot_svd_reduction(X, labels, color_labels=[], title=''):
    if len(color_labels) == 0:
        color_labels = labels

    max_label = 0
    for label in color_labels:
        if is_number(label):
            num = float(label)
            if num > max_label:
                max_label = num

    svd = TruncatedSVD()
    reduced_X = svd.fit_transform(X)
    x = reduced_X[:, 0]
    y = reduced_X[:, 1]
    # plt.plot(x,y, 'ro')
    fig, ax = plt.subplots()
    ax.scatter(x, y, s=[0 for i in x])

    colors = ['blue', 'green', 'red', 'cyan', 'magenta', 'yellow', 'black', '#FFA500']
    label_to_color = {}
    color_index = 0
    color = 'black'

    for i, (label, color_label) in enumerate(zip(labels, color_labels)):
        if max_label != 0:
            c = float(color_label) / max_label
            col = (c, 0, 1 - c)
            # if c > 0.7:
            #     col = 'blue'
            # if 0.3 < c < 0.7:
            #     col = 'purple'
            # if c < 0.3:
            #     col = 'red'
            ax.annotate(label, (x[i], y[i]), (x[i], y[i]), color=col)
        else:
            if color_label in label_to_color:
                color = label_to_color[color_label]
            else:
                color_index = (color_index + 1) % len(colors)
                label_to_color[color_label] = colors[color_index]
                color = colors[color_index]
            ax.annotate(label, (x[i], y[i]), (x[i], y[i]), color=color)
    if title != '':
        ax.set_title(title)


def init_model(dev_path, feat_input_dim, hidden_dim, input_dim, layers, results_file_path, test_path, train_path):
    # load train and test data
    (train_words, train_lemmas, train_feat_dicts) = prepare_sigmorphon_data.load_data(train_path)
    (dev_words, dev_lemmas, dev_feat_dicts) = prepare_sigmorphon_data.load_data(dev_path)
    (test_words, test_lemmas, test_feat_dicts) = prepare_sigmorphon_data.load_data(test_path)
    alphabet, feature_types = prepare_sigmorphon_data.get_alphabet(train_words, train_lemmas, train_feat_dicts)

    # used for character dropout
    alphabet.append(NULL)
    alphabet.append(UNK)

    # used during decoding
    alphabet.append(EPSILON)
    alphabet.append(BEGIN_WORD)
    alphabet.append(END_WORD)

    # add indices to alphabet - used to indicate when copying from lemma to word
    for marker in [str(i) for i in xrange(3 * MAX_PREDICTION_LEN)]:
        alphabet.append(marker)

    # indicates the FST to step forward in the input
    alphabet.append(STEP)

    # char 2 int
    alphabet_index = dict(zip(alphabet, range(0, len(alphabet))))
    inverse_alphabet_index = {index: char for char, index in alphabet_index.items()}

    # feat 2 int
    feature_alphabet = common.get_feature_alphabet(train_feat_dicts)
    feature_alphabet.append(UNK_FEAT)
    feat_index = dict(zip(feature_alphabet, range(0, len(feature_alphabet))))

    model_file_name = results_file_path + '_bestmodel.txt'

    # load model and everything else needed for prediction
    initial_model, encoder_frnn, encoder_rrnn, decoder_rnn = hard_attention.load_best_model(
        alphabet,
        results_file_path,
        input_dim,
        hidden_dim,
        layers,
        feature_alphabet,
        feat_input_dim,
        feature_types)

    print 'loaded existing model successfully'
    return (alphabet_index, decoder_rnn, encoder_frnn, encoder_rrnn, feat_index, feature_types, initial_model,
            inverse_alphabet_index, dev_words, dev_lemmas, dev_feat_dicts)


if __name__ == '__main__':
    arguments = docopt(__doc__)
    ts = time.time()
    st = datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d_%H:%M:%S')

    # default values
    if arguments['TRAIN_PATH']:
        train_path_param = arguments['TRAIN_PATH']
    else:
        train_path_param = '/Users/roeeaharoni/research_data/sigmorphon2016-master/data/turkish-task1-train'
    if arguments['DEV_PATH']:
        dev_path_param = arguments['DEV_PATH']
    else:
        dev_path_param = '/Users/roeeaharoni/research_data/sigmorphon2016-master/data/turkish-task1-dev'
    if arguments['TEST_PATH']:
        test_path_param = arguments['TEST_PATH']
    else:
        test_path_param = '/Users/roeeaharoni/research_data/sigmorphon2016-master/data/turkish-task1-test'
    if arguments['RESULTS_PATH']:
        results_file_path_param = arguments['RESULTS_PATH']
    else:
        results_file_path_param = \
            '/Users/roeeaharoni/Dropbox/phd/research/morphology/inflection_generation/results/results_' + st + '.txt'
    if arguments['SIGMORPHON_PATH']:
        sigmorphon_root_dir_param = arguments['SIGMORPHON_PATH'][0]
    else:
        sigmorphon_root_dir_param = '/Users/roeeaharoni/research_data/sigmorphon2016-master/'
    if arguments['--input']:
        input_dim_param = int(arguments['--input'])
    else:
        input_dim_param = INPUT_DIM
    if arguments['--hidden']:
        hidden_dim_param = int(arguments['--hidden'])
    else:
        hidden_dim_param = HIDDEN_DIM
    if arguments['--feat-input']:
        feat_input_dim_param = int(arguments['--feat-input'])
    else:
        feat_input_dim_param = FEAT_INPUT_DIM
    if arguments['--epochs']:
        epochs_param = int(arguments['--epochs'])
    else:
        epochs_param = EPOCHS
    if arguments['--layers']:
        layers_param = int(arguments['--layers'])
    else:
        layers_param = LAYERS
    if arguments['--optimization']:
        optimization_param = arguments['--optimization']
    else:
        optimization_param = OPTIMIZATION
    if arguments['--reg']:
        regularization_param = float(arguments['--reg'])
    else:
        regularization_param = REGULARIZATION
    if arguments['--learning']:
        learning_rate_param = float(arguments['--learning'])
    else:
        learning_rate_param = LEARNING_RATE
    if arguments['--plot']:
        plot_param = True
    else:
        plot_param = False
    if arguments['--override']:
        override_param = True
    else:
        override_param = False

    print arguments

    main(train_path_param, dev_path_param, test_path_param, results_file_path_param, sigmorphon_root_dir_param,
         input_dim_param, hidden_dim_param, feat_input_dim_param, epochs_param, layers_param, optimization_param,
         regularization_param, learning_rate_param, plot_param, override_param)
