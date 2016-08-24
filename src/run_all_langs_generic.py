"""Runs the script on all langs in parallel

Usage:
  run_all_langs_generic.py [--cnn-mem MEM][--input=INPUT] [--feat-input=FEAT][--hidden=HIDDEN] [--epochs=EPOCHS]
  [--layers=LAYERS] [--optimization=OPTIMIZATION] [--pool=POOL] [--langs=LANGS] [--script=SCRIPT] [--prefix=PREFIX]
  [--augment] [--merged] [--task=TASK] [--ensemble]
  SRC_PATH RESULTS_PATH SIGMORPHON_PATH...

Arguments:
  SRC_PATH  source files directory path
  RESULTS_PATH  results file to be written
  SIGMORPHON_PATH   sigmorphon root containing data, src dirs

Options:
  -h --help                     show this help message and exit
  --cnn-mem MEM                 allocates MEM bytes for (py)cnn
  --input=INPUT                 input vector dimensions
  --feat-input=FEAT             feature input vector dimension
  --hidden=HIDDEN               hidden layer dimensions
  --epochs=EPOCHS               amount of training epochs
  --layers=LAYERS               amount of layers in lstm network
  --optimization=OPTIMIZATION   chosen optimization method ADAM/SGD/ADAGRAD/MOMENTUM
  --pool=POOL                   amount of processes in pool
  --langs=LANGS                 languages separated by comma
  --script=SCRIPT               the training script to run
  --prefix=PREFIX               the output files prefix
  --augment                     whether to perform data augmentation
  --merged                      whether to train on train+dev merged
  --task=TASK                   the current task to train
  --ensemble                    the amount of ensemble models to train, 1 if not mentioned
"""

import os
import time
import datetime
import docopt
from multiprocessing import Pool


# default values
INPUT_DIM = 200
FEAT_INPUT_DIM = 20
HIDDEN_DIM = 200
EPOCHS = 1
LAYERS = 2
OPTIMIZATION = 'ADAM'
POOL = 4
LANGS = ['russian', 'georgian', 'finnish', 'arabic', 'navajo', 'spanish', 'turkish', 'german',
         'hungarian', 'maltese']
CNN_MEM = 9096


def main(src_dir, results_dir, sigmorphon_root_dir, input_dim, hidden_dim, epochs, layers,
         optimization, feat_input_dim, pool_size, langs, script, prefix, task, augment, merged, ensemble):
    parallelize_training = True
    params = []
    print 'now training langs: ' + str(langs)
    for lang in langs:
        params.append([CNN_MEM, epochs, feat_input_dim, hidden_dim, input_dim, lang, layers, optimization, results_dir,
                    sigmorphon_root_dir, src_dir, script, prefix, task, augment, merged, ensemble])


    # train models for each lang in parallel or in loop
    if parallelize_training:
        pool = Pool(int(pool_size), maxtasksperchild=1)
        print 'now training {0} langs in parallel'.format(len(langs))
        pool.map(train_language_wrapper, params)
    else:
        print 'now training {0} langs in loop'.format(len(langs))
        for p in params:
            train_language(*p)
    print 'finished training all models'


def train_language_wrapper(params):
    train_language(*params)


def train_language(cnn_mem, epochs, feat_input_dim, hidden_dim, input_dim, lang, layers, optimization, results_dir,
                sigmorphon_root_dir, src_dir, script, prefix, task, augment, merged, ensemble):

    if augment:
        augment_str='--augment'
    else:
        augment_str=''

    start = time.time()
    os.chdir(src_dir)

    # train ensemble models in parallel
    for e in xrange(ensemble):
        if ensemble != 1:
            prefix += '_ens_{}'.format(e)

        if merged:
            # train on train+dev, evaluate on dev for early stopping
            os.system('python {0} --cnn-mem {1} --input={2} --hidden={3} \
                --feat-input={4} --epochs={5} --layers={6} --optimization {7} {13}\
                ../data/sigmorphon_train_dev_merged/{9}-task{12}-merged \
                {8}/data/{9}-task{12}-dev \
                {10}/{11}_{9}-results.txt \
                {8}'.format(script, cnn_mem, input_dim, hidden_dim, feat_input_dim, epochs, layers, optimization,
                            sigmorphon_root_dir, lang, results_dir, prefix, task, augment_str))
        else:
            # train on train, evaluate on dev for early stopping
            os.system('python {0} --cnn-mem {1} --input={2} --hidden={3} \
                --feat-input={4} --epochs={5} --layers={6} --optimization {7} {13}\
                {8}/data/{9}-task{12}-train \
                {8}/data/{9}-task{12}-dev \
                {10}/{11}_{9}-results.txt \
                {8}'.format(script, cnn_mem, input_dim, hidden_dim, feat_input_dim, epochs, layers, optimization,
                            sigmorphon_root_dir, lang, results_dir, prefix, task, augment_str))

    end = time.time()
    print 'finished ' + lang + ' in ' + str(ms_to_timestring(end - start))


def ms_to_timestring(ms):
    return str(datetime.timedelta(ms))


def evaluate_baseline(lang, results_dir, sig_root):
    os.chdir(sig_root + '/src/baseline')

    # run baseline system
    os.system('./baseline.py --task=1 --language={0} \
        --path={1}/data/ > {2}/baseline_{0}_task1_predictions.txt'.format(lang, sig_root, results_dir))
    os.chdir(sig_root + '/src')

    # eval baseline system
    os.system('python evalm.py --gold ../data/{0}-task1-dev --guesses \
        {1}/baseline_{0}_task1_predictions.txt'.format(lang, results_dir))


if __name__ == '__main__':
    arguments = docopt.docopt(__doc__)

    ts = time.time()
    st = datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d_%H:%M:%S')

    # default values
    if arguments['SRC_PATH']:
        src_dir = arguments['SRC_PATH']
    else:
        src_dir = '/Users/roeeaharoni/GitHub/morphological-reinflection/src/'
    if arguments['RESULTS_PATH']:
        results_dir = arguments['RESULTS_PATH']
    else:
        results_dir = '/Users/roeeaharoni/Dropbox/phd/research/morphology/inflection_generation/results/'
    if arguments['SIGMORPHON_PATH']:
        sigmorphon_root_dir = arguments['SIGMORPHON_PATH'][0]
    else:
        sigmorphon_root_dir = '/Users/roeeaharoni/research_data/sigmorphon2016-master/'
    if arguments['--input']:
        input_dim = int(arguments['--input'])
    else:
        input_dim = INPUT_DIM
    if arguments['--hidden']:
        hidden_dim = int(arguments['--hidden'])
    else:
        hidden_dim = HIDDEN_DIM
    if arguments['--feat-input']:
        feat_input_dim = int(arguments['--feat-input'])
    else:
        feat_input_dim = FEAT_INPUT_DIM
    if arguments['--epochs']:
        epochs = int(arguments['--epochs'])
    else:
        epochs = EPOCHS
    if arguments['--layers']:
        layers = int(arguments['--layers'])
    else:
        layers = LAYERS
    if arguments['--optimization']:
        optimization = arguments['--optimization']
    else:
        optimization = OPTIMIZATION
    if arguments['--pool']:
        pool_size = arguments['--pool']
    else:
        pool_size = POOL
    if arguments['--langs']:
        langs_param = [l.strip() for l in arguments['--langs'].split(',')]
    else:
        langs_param = LANGS
    if arguments['--script']:
        script_param = arguments['--script']
    else:
        print 'script is mandatory'
        raise ValueError
    if arguments['--prefix']:
        prefix_param = arguments['--prefix']
    else:
        print 'prefix is mandatory'
        raise ValueError
    if arguments['--task']:
        task_param = arguments['--task']
    else:
        task_param = '1'
    if arguments['--augment']:
        augment_param = True
    else:
        augment_param = False
    if arguments['--merged']:
        merged_param = True
    else:
        merged_param = False
    if arguments['--ensemble']:
        ensemble_param = int(arguments['--ensemble'])
    else:
        ensemble_param = 1

    print arguments

    main(src_dir, results_dir, sigmorphon_root_dir, input_dim, hidden_dim, epochs, layers,
         optimization, feat_input_dim, pool_size, langs_param, script_param, prefix_param, task_param,
         augment_param, merged_param, ensemble_param)
