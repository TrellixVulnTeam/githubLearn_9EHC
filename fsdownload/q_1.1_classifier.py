# coding=utf-8
# Copyright 2018 The Google AI Language Team Authors and The HuggingFace Inc. team.
# Copyright (c) 2018, NVIDIA CORPORATION.  All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""BERT finetuning runner."""

from __future__ import absolute_import, division, print_function

import argparse
import csv
import logging
import os
import random
import sys

import numpy as np
import torch
from torch.utils.data import (DataLoader, RandomSampler, SequentialSampler,
                              TensorDataset)
from torch.utils.data.distributed import DistributedSampler
from tqdm import tqdm, trange

from torch.nn import CrossEntropyLoss, MSELoss
from scipy.stats import pearsonr, spearmanr
from sklearn.metrics import matthews_corrcoef, f1_score, accuracy_score

from pytorch_pretrained_bert import file_utils#又见了，小伙子
from pytorch_pretrained_bert import modeling
from pytorch_pretrained_bert import tokenization
from pytorch_pretrained_bert import optimization

logger = logging.getLogger(__name__)

class InputExample(object):
    """A single training/test example for simple sequence classification."""

    def __init__(self, guid,question, text_a, text_b=None, label=None):
        """Constructs a InputExample.

        Args:
            guid: Unique id for the example.
            text_a: string. The untokenized text of the first sequence. For single
            sequence tasks, only this sequence must be specified.
            text_b: (Optional) string. The untokenized text of the second sequence.
            Only must be specified for sequence pair tasks.
            label: (Optional) string. The label of the example. This should be
            specified for train and dev examples, but not for test examples.
        """
        self.guid = guid
        self.question = question
        self.text_a = text_a
        self.text_b = text_b
        self.label = label


class InputFeatures(object):
    """A single set of features of data."""

    def __init__(self, input_ids, input_mask, segment_ids, label_id):
        self.input_ids = input_ids
        self.input_mask = input_mask
        self.segment_ids = segment_ids
        self.label_id = label_id


class DataProcessor(object):
    """Base class for data converters for sequence classification data sets."""

    def get_train_examples(self, data_dir):
        """Gets a collection of `InputExample`s for the train set."""
        raise NotImplementedError()

    def get_dev_examples(self, data_dir):
        """Gets a collection of `InputExample`s for the dev set."""
        raise NotImplementedError()

    def get_valid_examples(self, data_dir):
        """See base class."""
        return self._create_examples(
            self._read_tsv(os.path.join(data_dir, "dev.tsv")), "dev")
    def get_labels(self):
        """Gets the list of labels for this data set."""
        raise NotImplementedError()

    @classmethod
    def _read_tsv(cls, input_file, quotechar=None):
        """Reads a tab separated value file."""
        with open(input_file, "r", encoding="utf-8") as f:
            reader = csv.reader(f, delimiter="\t", quotechar=quotechar)
            lines = []
            for line in reader:
                if sys.version_info[0] == 2:
                    line = list(str(cell, 'utf-8') for cell in line)
                lines.append(line)
            return lines


class MrpcProcessor(DataProcessor):
    """Processor for the MRPC data set (GLUE version)."""

    def get_train_examples(self, data_dir):
        """See base class."""
        logger.info("LOOKING AT {}".format(os.path.join(data_dir, "train.tsv")))
        return self._create_examples(
            self._read_tsv(os.path.join(data_dir, "train.tsv")), "train")

    def get_dev_examples(self, data_dir):
        """See base class."""
        return self._create_examples(
            self._read_tsv(os.path.join(data_dir, "dev.tsv")), "dev")


    def get_labels(self):
        """See base class."""
        return ["0", "1"]

    def _create_examples(self, lines, set_type):
        """Creates examples for the training and dev sets."""
        examples = []
        for (i, line) in enumerate(lines):
            if i == 0:
                continue
            guid = "%s-%s" % (set_type, i)
            text_a = line[3]
            text_b = line[4]
            label = line[0]
            examples.append(
                InputExample(guid=guid, text_a=text_a, text_b=text_b, label=label))
        return examples

class SASProcessor(DataProcessor):
    """Processor for the Science Bank data set."""
    def __init__(self, n, eval_type):

        self.n_way = '{}way'.format(n)

        if eval_type == 'ua':
            eval_filename = "test-unseen-answers.txt"

        elif eval_type == 'ud':
            eval_filename = "test-unseen-domains.txt"

        elif eval_type == 'uq':
            eval_filename = "test-unseen-questions.txt"

        self.eval_file = eval_filename

        if n == 2:
            labels = ["incorrect", "correct"]
        elif n == 3:
            labels = ["incorrect", "correct", "contradictory"]
        elif n == 5:
            labels = ["irrelevant", "correct", "non_domain", "contradictory", "partially_correct_incomplete"]
        self.labels = labels 

        print("current running: n_way: {}, eval_file,: {}, labels: {}".format(self.n_way, self.eval_file, self, labels))


    def get_train_examples(self, data_dir):
        """See base class."""
        logger.info("LOOKING AT {}".format(os.path.join(data_dir, self.n_way, "newtrain.txt")))
        return self._create_examples(
            self._read_tsv(os.path.join(data_dir, self.n_way, "newtrain.txt")), "train")

    def get_dev_examples(self, data_dir):
        """See base class."""
        return self._create_examples(
            self._read_tsv(os.path.join(data_dir, self.n_way, self.eval_file)), "dev")

    def get_valid_examples(self, data_dir):
        """See base class."""
        return self._create_examples(
            self._read_tsv(os.path.join(data_dir,  "valid-unseen.txt")), "valid")

    def get_labels(self):
        """See base class."""
        return self.labels

    def _create_examples(self, lines, set_type):
        """Creates examples for the training and dev sets."""
        examples = []
        for (i, line) in enumerate(lines):
            if i == 0:
                continue
            guid = "%s-%s" % (set_type, i)
            question = line[1]
            text_a = line[2]
            text_b = line[4]
            label = line[5]
            if i <= 5:
                logger.info("**** {} samples of sciencesbank ****".format(self.n_way))
                logger.info("text_a: [{}] test_b: [{}] label: [{}]".format(text_a, text_b, label))
            examples.append(
                InputExample(guid=guid, question=question,text_a=text_a, text_b=text_b, label=label))
        return examples

class MnliProcessor(DataProcessor):
    """Processor for the MultiNLI data set (GLUE version)."""

    def get_train_examples(self, data_dir):
        """See base class."""
        return self._create_examples(
            self._read_tsv(os.path.join(data_dir, "train.tsv")), "train")

    def get_dev_examples(self, data_dir):
        """See base class."""
        return self._create_examples(
            self._read_tsv(os.path.join(data_dir, "dev_matched.tsv")),
            "dev_matched")

    def get_labels(self):
        """See base class."""
        return ["contradiction", "entailment", "neutral"]

    def _create_examples(self, lines, set_type):
        """Creates examples for the training and dev sets."""
        examples = []
        for (i, line) in enumerate(lines):
            if i == 0:
                continue
            guid = "%s-%s" % (set_type, line[0])
            text_a = line[8]
            text_b = line[9]
            label = line[-1]
            examples.append(
                InputExample(guid=guid, text_a=text_a, text_b=text_b, label=label))
        return examples


class MnliMismatchedProcessor(MnliProcessor):
    """Processor for the MultiNLI Mismatched data set (GLUE version)."""

    def get_dev_examples(self, data_dir):
        """See base class."""
        return self._create_examples(
            self._read_tsv(os.path.join(data_dir, "dev_mismatched.tsv")),
            "dev_matched")


class ColaProcessor(DataProcessor):
    """Processor for the CoLA data set (GLUE version)."""

    def get_train_examples(self, data_dir):
        """See base class."""
        return self._create_examples(
            self._read_tsv(os.path.join(data_dir, "train.tsv")), "train")

    def get_dev_examples(self, data_dir):
        """See base class."""
        return self._create_examples(
            self._read_tsv(os.path.join(data_dir, "dev.tsv")), "dev")

    def get_labels(self):
        """See base class."""
        return ["0", "1"]

    def _create_examples(self, lines, set_type):
        """Creates examples for the training and dev sets."""
        examples = []
        # lines是enumerate的名字。i 是enumerate里面的序号，默认是0，递增。line是enumerate里面的元素
        for (i, line) in enumerate(lines):
            guid = "%s-%s" % (set_type, i)
            text_a = line[3]
            label = line[1]
            examples.append(
                InputExample(guid=guid, text_a=text_a, text_b=None, label=label))
        return examples


class Sst2Processor(DataProcessor):
    """Processor for the SST-2 data set (GLUE version)."""

    def get_train_examples(self, data_dir):
        """See base class."""
        return self._create_examples(
            self._read_tsv(os.path.join(data_dir, "train.tsv")), "train")

    def get_dev_examples(self, data_dir):
        """See base class."""
        return self._create_examples(
            self._read_tsv(os.path.join(data_dir, "dev.tsv")), "dev")

    def get_labels(self):
        """See base class."""
        return ["0", "1"]

    def _create_examples(self, lines, set_type):
        """Creates examples for the training and dev sets."""
        examples = []
        for (i, line) in enumerate(lines):
            if i == 0:
                continue
            guid = "%s-%s" % (set_type, i)
            text_a = line[0]
            label = line[1]
            examples.append(
                InputExample(guid=guid, text_a=text_a, text_b=None, label=label))
        return examples


class StsbProcessor(DataProcessor):
    """Processor for the STS-B data set (GLUE version)."""

    def get_train_examples(self, data_dir):
        """See base class."""
        return self._create_examples(
            self._read_tsv(os.path.join(data_dir, "train.tsv")), "train")

    def get_dev_examples(self, data_dir):
        """See base class."""
        return self._create_examples(
            self._read_tsv(os.path.join(data_dir, "dev.tsv")), "dev")

    def get_labels(self):
        """See base class."""
        return [None]

    def _create_examples(self, lines, set_type):
        """Creates examples for the training and dev sets."""
        examples = []
        for (i, line) in enumerate(lines):
            if i == 0:
                continue
            guid = "%s-%s" % (set_type, line[0])
            text_a = line[7]
            text_b = line[8]
            label = line[-1]
            examples.append(
                InputExample(guid=guid, text_a=text_a, text_b=text_b, label=label))
        return examples


class QqpProcessor(DataProcessor):
    """Processor for the STS-B data set (GLUE version)."""

    def get_train_examples(self, data_dir):
        """See base class."""
        return self._create_examples(
            self._read_tsv(os.path.join(data_dir, "train.tsv")), "train")

    def get_dev_examples(self, data_dir):
        """See base class."""
        return self._create_examples(
            self._read_tsv(os.path.join(data_dir, "dev.tsv")), "dev")

    def get_labels(self):
        """See base class."""
        return ["0", "1"]

    def _create_examples(self, lines, set_type):
        """Creates examples for the training and dev sets."""
        examples = []
        for (i, line) in enumerate(lines):
            if i == 0:
                continue
            guid = "%s-%s" % (set_type, line[0])
            try:
                text_a = line[3]
                text_b = line[4]
                label = line[5].strip()
            except IndexError:
                continue
            examples.append(
                InputExample(guid=guid, text_a=text_a, text_b=text_b, label=label))
        return examples


class QnliProcessor(DataProcessor):
    """Processor for the STS-B data set (GLUE version)."""

    def get_train_examples(self, data_dir):
        """See base class."""
        return self._create_examples(
            self._read_tsv(os.path.join(data_dir, "train.tsv")), "train")

    def get_dev_examples(self, data_dir):
        """See base class."""
        return self._create_examples(
            self._read_tsv(os.path.join(data_dir, "dev.tsv")), 
            "dev_matched")

    def get_labels(self):
        """See base class."""
        return ["entailment", "not_entailment"]

    def _create_examples(self, lines, set_type):
        """Creates examples for the training and dev sets."""
        examples = []
        for (i, line) in enumerate(lines):
            if i == 0:
                continue
            guid = "%s-%s" % (set_type, line[0])
            text_a = line[1]
            text_b = line[2]
            label = line[-1]
            examples.append(
                InputExample(guid=guid, text_a=text_a, text_b=text_b, label=label))
        return examples


class RteProcessor(DataProcessor):
    """Processor for the RTE data set (GLUE version)."""

    def get_train_examples(self, data_dir):
        """See base class."""
        return self._create_examples(
            self._read_tsv(os.path.join(data_dir, "train.tsv")), "train")

    def get_dev_examples(self, data_dir):
        """See base class."""
        return self._create_examples(
            self._read_tsv(os.path.join(data_dir, "dev.tsv")), "dev")

    def get_labels(self):
        """See base class."""
        return ["entailment", "not_entailment"]

    def _create_examples(self, lines, set_type):
        """Creates examples for the training and dev sets."""
        examples = []
        for (i, line) in enumerate(lines):
            if i == 0:
                continue
            guid = "%s-%s" % (set_type, line[0])
            text_a = line[1]
            text_b = line[2]
            label = line[-1]
            examples.append(
                InputExample(guid=guid, text_a=text_a, text_b=text_b, label=label))
        return examples


class WnliProcessor(DataProcessor):
    """Processor for the WNLI data set (GLUE version)."""

    def get_train_examples(self, data_dir):
        """See base class."""
        return self._create_examples(
            self._read_tsv(os.path.join(data_dir, "train.tsv")), "train")

    def get_dev_examples(self, data_dir):
        """See base class."""
        return self._create_examples(
            self._read_tsv(os.path.join(data_dir, "dev.tsv")), "dev")

    def get_labels(self):
        """See base class."""
        return ["0", "1"]

    def _create_examples(self, lines, set_type):
        """Creates examples for the training and dev sets."""
        examples = []
        for (i, line) in enumerate(lines):
            if i == 0:
                continue
            guid = "%s-%s" % (set_type, line[0])
            text_a = line[1]
            text_b = line[2]
            label = line[-1]
            examples.append(
                InputExample(guid=guid, text_a=text_a, text_b=text_b, label=label))
        return examples


def convert_examples_to_features(examples, label_list, max_seq_length,
                                 tokenizer, output_mode):
    """Loads a data file into a list of `InputBatch`s."""

    label_map = {label : i for i, label in enumerate(label_list)}

    features = []
    both_answers = []
    textab = ""
    for (ex_index, example) in enumerate(examples):
        if ex_index % 10000 == 0:
            logger.info("Writing example %d of %d" % (ex_index, len(examples)))
        textab = example.text_b
        tokens_a = tokenizer.tokenize(example.text_a)
        tokens_q = tokenizer.tokenize(example.question)
        tokens_b = None
        if example.text_b:
            tokens_b = tokenizer.tokenize(example.text_b)
            # Modifies `tokens_a` and `tokens_b` in place so that the total
            # length is less than the specified length.
            # Account for [CLS], [SEP], [SEP] with "- 3"
            _truncate_seq_pair(tokens_q,tokens_a, tokens_b, max_seq_length - 94)
        else:
            # Account for [CLS] and [SEP] with "- 2"
            if len(tokens_a) > max_seq_length - 2:
                tokens_a = tokens_a[:(max_seq_length - 2)]

        tokens = ["[CLS]"] + tokens_q + ["[SEP]"]
        segment_ids = [1] * len(tokens)

        tokens +=  tokens_a + ["[SEP]"]
        segment_ids += [0] * (len(tokens_a) + 1)

        if tokens_b:
            tokens += tokens_b + ["[SEP]"]
            segment_ids += [1] * (len(tokens_b) + 1)

        input_ids = tokenizer.convert_tokens_to_ids(tokens)

        # The mask has 1 for real tokens and 0 for padding tokens. Only real
        # tokens are attended to.
        input_mask = [1] * len(input_ids)

        # Zero-pad up to the sequence length.
        padding = [0] * (max_seq_length - len(input_ids))
        input_ids += padding
        input_mask += padding
        segment_ids += padding
        assert len(input_ids) == max_seq_length
        assert len(input_mask) == max_seq_length
        assert len(segment_ids) == max_seq_length

        if output_mode == "classification":
            label_id = label_map[example.label.strip()]
        elif output_mode == "regression":
            label_id = float(example.label)
        else:
            raise KeyError(output_mode)

        if ex_index < 5:
            logger.info("*** Example ***")
            logger.info("guid: %s" % (example.guid))
            logger.info("tokens: %s" % " ".join(
                    [str(x) for x in tokens]))
            logger.info("input_ids: %s" % " ".join([str(x) for x in input_ids]))
            logger.info("input_mask: %s" % " ".join([str(x) for x in input_mask]))
            logger.info(
                    "segment_ids: %s" % " ".join([str(x) for x in segment_ids]))
            logger.info("label: %s (id = %d)" % (example.label, label_id))
        # print("features len :",len(features))
        features.append(
                InputFeatures(input_ids=input_ids,
                              input_mask=input_mask,
                              segment_ids=segment_ids,
                              label_id=label_id))


        both_answers.append(textab)#添加到该列表

        textab = ""#清空本条数据

    return features,both_answers


def _truncate_seq_pair(token_q,tokens_a, tokens_b, max_length):
    """Truncates a sequence pair in place to the maximum length."""

    # This is a simple heuristic which will always truncate the longer sequence
    # one token at a time. This makes more sense than truncating an equal percent
    # of tokens from each, since if one sequence is very short then each token
    # that's truncated likely contains more information than a longer sequence.
    while (len(token_q) > 90):
        token_q.pop()
    while True:
        total_length = len(tokens_a) + len(tokens_b)
        if total_length <= max_length:
            break
        if len(tokens_a) > len(tokens_b):
            tokens_a.pop()
        else:
            tokens_b.pop()

def simple_accuracy(preds, labels):
    return (preds == labels).mean()

def acc_and_f1(preds, labels):
    acc = simple_accuracy(preds, labels)
    f1 = f1_score(y_true=labels, y_pred=preds)
    return {
        "acc": acc,
        "f1": f1,
        "acc_and_f1": (acc + f1) / 2,
    }

def acc_and_wm_f1(preds,labels):

    acc = accuracy_score(y_true=labels, y_pred=preds)
    w_f1 = f1_score(y_true=labels, y_pred=preds, average='weighted')
    m_f1 = f1_score(y_true=labels, y_pred=preds, average='macro')
    return {
        "acc": acc,
        "m_f1": m_f1,
        "w_f1": w_f1,
    }

def pearson_and_spearman(preds, labels):
    pearson_corr = pearsonr(preds, labels)[0]
    spearman_corr = spearmanr(preds, labels)[0]
    return {
        "pearson": pearson_corr,
        "spearmanr": spearman_corr,
        "corr": (pearson_corr + spearman_corr) / 2,
    }

def compute_metrics(task_name, preds, labels):
    assert len(preds) == len(labels)
    if task_name == "cola":
        return {"mcc": matthews_corrcoef(labels, preds)}
    elif task_name == "sst-2":
        return {"acc": simple_accuracy(preds, labels)}
    elif task_name == "mrpc":
        return acc_and_f1(preds, labels)
    elif task_name == "sts-b":
        return pearson_and_spearman(preds, labels)
    elif task_name == "qqp":
        return acc_and_f1(preds, labels)
    elif task_name == "mnli":
        return {"acc": simple_accuracy(preds, labels)}
    elif task_name == "mnli-mm":
        return {"acc": simple_accuracy(preds, labels)}
    elif task_name == "qnli":
        return {"acc": simple_accuracy(preds, labels)}
    elif task_name == "rte":
        return {"acc": simple_accuracy(preds, labels)}
    elif task_name == "wnli":
        return {"acc": simple_accuracy(preds, labels)}
    elif task_name == "sas":
        return {"acc": acc_and_wm_f1(preds, labels)}
    else:
        raise KeyError(task_name)

def print_err(preds,labels,both_answers,epoch):

    with open("/home/gylv/EAAI-25-master/src/model/error.txt","a+") as w:
        w.write("第%d轮\n：" % epoch)
        for i in range(len(preds)):
            if (preds[i] != labels[i]):
                w.write("第%d条: %s \n label=%d,pred=%d\n" % (i + 1, both_answers[i],labels[i],preds[i]))


def main():

    parser = argparse.ArgumentParser()

    ## Required parameters
    parser.add_argument("--train_data_dir",
                        default=None,
                        type=str,
                        required=True,
                        help="The input test data dir. Should contain the .tsv files (or other data files) for the task.")

    
    parser.add_argument("--valid_data_dir",
                        default=None,
                        type=str,
                        required=True,
                        help="The input valid data dir. Should contain the .tsv files (or other data files) for the task.")


    parser.add_argument("--test_data_dir",
                        default=None,
                        type=str,
                        required=True,
                        help="The input test data dir. Should contain the .tsv files (or other data files) for the task.")
    
    parser.add_argument("--bert_model", default=None, type=str, required=True,
                        help="Bert pre-trained model selected in the list: bert-base-uncased, "
                        "bert-large-uncased, bert-base-cased, bert-large-cased, bert-base-multilingual-uncased, "
                        "bert-base-multilingual-cased, bert-base-chinese.")
    parser.add_argument("--task_name",
                        default=None,
                        type=str,
                        required=True,
                        help="The name of the task to train.")
    parser.add_argument("--output_dir",
                        default=None,
                        type=str,
                        required=True,
                        help="The output directory where the model predictions and checkpoints will be written.")

    ## Other parameters
    parser.add_argument("--cache_dir",
                        default="",
                        type=str,
                        help="Where do you want to store the pre-trained models downloaded from s3")
    parser.add_argument("--max_seq_length",
                        default=128,
                        type=int,
                        help="The maximum total input sequence length after WordPiece tokenization. \n"
                             "Sequences longer than this will be truncated, and sequences shorter \n"
                             "than this will be padded.")
    parser.add_argument("--do_train",
                        action='store_true',
                        help="Whether to run training.")
    parser.add_argument("--do_eval",
                        action='store_true',
                        help="Whether to run eval on the dev set.")

    parser.add_argument("--n",
                        default=2,
                        type=int,
                        help="choose way of n, 2way, 3way, 5way")

    parser.add_argument("--eval_type",
                        default="ua",
                        type=str,
                        help="choose one of string in (ua uq ud)")
        
    parser.add_argument("--do_lower_case",
                        action='store_true',
                        help="Set this flag if you are using an uncased model.")
    parser.add_argument("--train_batch_size",
                        default=32,
                        type=int,
                        help="Total batch size for training.")
    parser.add_argument("--eval_batch_size",
                        default=8,
                        type=int,
                        help="Total batch size for eval.")
    parser.add_argument("--learning_rate",
                        default=5e-5,
                        type=float,
                        help="The initial learning rate for Adam.")
    parser.add_argument("--num_train_epochs",
                        default=3.0,
                        type=float,
                        help="Total number of training epochs to perform.")
    parser.add_argument("--warmup_proportion",
                        default=0.1,
                        type=float,
                        help="Proportion of training to perform linear learning rate warmup for. "
                             "E.g., 0.1 = 10%% of training.")
    parser.add_argument("--no_cuda",
                        action='store_true',
                        help="Whether not to use CUDA when available")
    parser.add_argument("--local_rank",
                        type=int,
                        default=-1,
                        help="local_rank for distributed training on gpus")
    parser.add_argument('--seed',
                        type=int,
                        default=42,
                        help="random seed for initialization")
    parser.add_argument('--gradient_accumulation_steps',
                        type=int,
                        default=1,
                        help="Number of updates steps to accumulate before performing a backward/update pass.")
    parser.add_argument('--fp16',
                        action='store_true',
                        help="Whether to use 16-bit float precision instead of 32-bit")
    parser.add_argument('--loss_scale',
                        type=float, default=0,
                        help="Loss scaling to improve fp16 numeric stability. Only used when fp16 set to True.\n"
                             "0 (default value): dynamic loss scaling.\n"
                             "Positive power of 2: static loss scaling value.\n")
    parser.add_argument('--server_ip', type=str, default='', help="Can be used for distant debugging.")
    parser.add_argument('--server_port', type=str, default='', help="Can be used for distant debugging.")
    args = parser.parse_args()

    if args.server_ip and args.server_port:
        # Distant debugging - see https://code.visualstudio.com/docs/python/debugging#_attach-to-a-local-script
        import ptvsd
        print("Waiting for debugger attach")
        ptvsd.enable_attach(address=(args.server_ip, args.server_port), redirect_output=True)
        ptvsd.wait_for_attach()

    processors = {
        "cola": ColaProcessor,
        "mnli": MnliProcessor,
        "mnli-mm": MnliMismatchedProcessor,
        "mrpc": MrpcProcessor,
        "sst-2": Sst2Processor,
        "sts-b": StsbProcessor,
        "qqp": QqpProcessor,
        "qnli": QnliProcessor,
        "rte": RteProcessor,
        "wnli": WnliProcessor,
        "sas": SASProcessor,
    }

    output_modes = {
        "cola": "classification",
        "mnli": "classification",
        "mrpc": "classification",
        "sst-2": "classification",
        "sts-b": "regression",
        "qqp": "classification",
        "qnli": "classification",
        "rte": "classification",
        "wnli": "classification",
        "sas": "classification",
    }
    #设置要使用的gpu
    os.environ["CUDA_VISIBLE_DEVICES"] = "1"  # 只看到第2块gpu
    n_gpu = torch.cuda.device_count()
    logging.basicConfig(format = '%(asctime)s - %(levelname)s - %(name)s -  %(lineno)s -   %(message)s',
                        datefmt = '%m/%d/%Y %H:%M:%S',
                        level = logging.INFO if args.local_rank in [-1, 0] else logging.WARN,
                        filename = "/home/gylv/EAAI-25-master/src/model/mylog.txt"
                        )

    logger.info("n_gpu: {}, distributed training: {}, 16-bits training: {}".format(
        n_gpu, bool(args.local_rank != -1), args.fp16))

    if args.gradient_accumulation_steps < 1:
        raise ValueError("Invalid gradient_accumulation_steps parameter: {}, should be >= 1".format(
                            args.gradient_accumulation_steps))

    args.train_batch_size = args.train_batch_size // args.gradient_accumulation_steps

    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    if n_gpu > 0:
        torch.cuda.manual_seed_all(args.seed)

    if not args.do_train and not args.do_eval:
        raise ValueError("At least one of `do_train` or `do_eval` must be True.")

    if os.path.exists(args.output_dir) and os.listdir(args.output_dir) and args.do_train:
        raise ValueError("Output directory ({}) already exists and is not empty.".format(args.output_dir))
    if not os.path.exists(args.output_dir):
        os.makedirs(args.output_dir)

    task_name = args.task_name.lower()

    if task_name not in processors:
        raise ValueError("Task not found: %s" % (task_name))

    processor = None
    if task_name == 'sas':
        processor = processors[task_name](args.n, args.eval_type)
    else:
        processor = processors[task_name]()#processor是字典，()创建该类实例
    output_mode = output_modes[task_name]

    label_list = processor.get_labels()
    num_labels = len(label_list)

    tokenizer = tokenization.BertTokenizer.from_pretrained(args.bert_model, do_lower_case=args.do_lower_case)

    train_examples = None
    num_train_optimization_steps = None
    if args.do_train:
        train_examples = processor.get_train_examples(args.train_data_dir)
        num_train_optimization_steps = int(
            len(train_examples) / args.train_batch_size / args.gradient_accumulation_steps) * args.num_train_epochs
        if args.local_rank != -1:
            num_train_optimization_steps = num_train_optimization_steps // torch.distributed.get_world_size()

    # Prepare model
    cache_dir = args.cache_dir if args.cache_dir else os.path.join(str(file_utils.PYTORCH_PRETRAINED_BERT_CACHE), 'distributed_{}'.format(args.local_rank))
    print(cache_dir)
    model = modeling.BertForSequenceClassification.from_pretrained(args.bert_model,cache_dir=cache_dir,
                                                                                    num_labels=num_labels)
    if args.fp16:
        model.half()

    model.cuda()

    # 分布式训练，多机多卡。并行训练，一机多卡
    if args.local_rank != -1:#分布式训练
        try:
            from apex.parallel import DistributedDataParallel as DDP
        except ImportError:
            raise ImportError("Please install apex from https://www.github.com/nvidia/apex to use distributed and fp16 training.")

        model = DDP(model)
    elif n_gpu > 1:#并行训练
        model = torch.nn.DataParallel(model)

    # Prepare optimizer
    param_optimizer = list(model.named_parameters())
    no_decay = ['bias', 'LayerNorm.bias', 'LayerNorm.weight']
    optimizer_grouped_parameters = [
        {'params': [p for n, p in param_optimizer if not any(nd in n for nd in no_decay)], 'weight_decay': 0.01},
        {'params': [p for n, p in param_optimizer if any(nd in n for nd in no_decay)], 'weight_decay': 0.0}
        ]
    if args.fp16:
        try:
            from apex.optimizers import FP16_Optimizer
            from apex.optimizers import FusedAdam
        except ImportError:
            raise ImportError("Please install apex from https://www.github.com/nvidia/apex to use distributed and fp16 training.")

        optimizer = FusedAdam(optimizer_grouped_parameters,
                              lr=args.learning_rate,
                              bias_correction=False,
                              max_grad_norm=1.0)
        if args.loss_scale == 0:
            optimizer = FP16_Optimizer(optimizer, dynamic_loss_scale=True)
        else:
            optimizer = FP16_Optimizer(optimizer, static_loss_scale=args.loss_scale)
        warmup_linear = optimization.WarmupLinearSchedule(warmup=args.warmup_proportion,
                                             t_total=num_train_optimization_steps)

    else:
        optimizer = optimization.BertAdam(optimizer_grouped_parameters,
                             lr=args.learning_rate,
                             warmup=args.warmup_proportion,
                             t_total=num_train_optimization_steps)


    def load_data(data_features,dataname,batch):

        all_input_ids = torch.tensor([f.input_ids for f in data_features], dtype=torch.long)
        all_input_mask = torch.tensor([f.input_mask for f in data_features], dtype=torch.long)
        all_segment_ids = torch.tensor([f.segment_ids for f in data_features], dtype=torch.long)
        if output_mode == "classification":
            label_ids = torch.tensor([f.label_id for f in data_features], dtype=torch.long)
        elif output_mode == "regression":
            label_ids = torch.tensor([f.label_id for f in data_features], dtype=torch.float)

        #每个特征封装在一起，一一对应
        data = TensorDataset(all_input_ids, all_input_mask, all_segment_ids,label_ids)

        if dataname == "train":
            data_sampler = RandomSampler(data)  # 随机采样器
        else:
            data_sampler = SequentialSampler(data)#顺序采样器

        data_loader = DataLoader(data, sampler=data_sampler, batch_size=batch)

        return data_loader,label_ids


    if args.do_train:
        # 加载traindata
        logger.info("***** Running training *****")
        logger.info("  Num examples = %d", len(train_examples))
        logger.info("  Batch size = %d", args.train_batch_size)
        logger.info("  Num steps = %d", num_train_optimization_steps)

        train_features,_ = convert_examples_to_features(
            train_examples, label_list, args.max_seq_length, tokenizer, output_mode)

        train_dataloader,_ = load_data(train_features,"train",args.train_batch_size)


        #加载testdata
    if args.do_eval and (args.local_rank == -1 or torch.distributed.get_rank() == 0):

        logger.info("***** Running evaluation *****")

        eval_examples = processor.get_dev_examples(args.test_data_dir)

        logger.info("  Num examples = %d", len(eval_examples))
        logger.info("  Batch size = %d", args.eval_batch_size)

        eval_features,test_both_answers = convert_examples_to_features(
            eval_examples, label_list, args.max_seq_length, tokenizer, output_mode)

        eval_dataloader,test_label_ids = load_data(eval_features,"test",args.eval_batch_size)

    #加载验证集
    if args.do_eval and (args.local_rank == -1 or torch.distributed.get_rank() == 0):
        logger.info("***** Running validation *****")
        valid_examples = processor.get_valid_examples(args.valid_data_dir)

        logger.info("  Num examples = %d", len(valid_examples))
        logger.info("  Batch size = %d", args.eval_batch_size)

        valid_features,_ = convert_examples_to_features(
            valid_examples, label_list, args.max_seq_length, tokenizer, output_mode)

        valid_dataloader,valid_label_ids = load_data(valid_features,"valid",args.eval_batch_size)

        #数据集加载完毕

        model.train()
        valid_preds = []
        preds = []  # 测试集的预测
        test_acc = []
        test_mf1 = []
        test_wf1 = []

        valid_acc = []
        valid_mf1 = []
        valid_wf1 = []

        train_loss = []
        loss_valid = []
        loss_test = []
        global_step = 0
        output_eval_file = os.path.join(args.output_dir, "results.txt")
        with open(output_eval_file, "a+") as writer:
            writer.write("\n幸福不是绝对的幸福，痛苦不是绝对的痛苦。幸福和痛苦可以相互转化。人们把这两个词分的太清楚，给的情绪心理反应太大。事实并不是这样的")
            writer.write("数据增强类型:%s\n" % (args.train_data_dir.split('/')[-1]))
            writer.write("最大序列长度:%d\n" % (args.max_seq_length))
            writer.write("轮数:%f\n" % (args.num_train_epochs))

        for epoch in trange(int(args.num_train_epochs), desc="Epoch"):

            tr_loss = 0#本epoch训练集的损失

            pbar = tqdm(train_dataloader, desc="Iteration")#一个epoch需要几个iteration，也就是需要几个batch
            for step, batch in enumerate(pbar):
                batch = tuple(t.cuda() for t in batch)
                input_ids, input_mask, segment_ids, label_ids = batch
                logits = model(input_ids, segment_ids, input_mask, labels=None)

                if output_mode == "classification":
                    loss_fct = CrossEntropyLoss()
                    loss = loss_fct(logits.view(-1, num_labels), label_ids.view(-1))
                elif output_mode == "regression":
                    loss_fct = MSELoss()
                    loss = loss_fct(logits.view(-1), label_ids.view(-1))

                if n_gpu > 1:
                    loss = loss.mean()# mean() to average on multi-gpu.
                if args.gradient_accumulation_steps > 1:
                    loss = loss / args.gradient_accumulation_steps

                if args.fp16:
                    optimizer.backward(loss)
                else:
                    loss.backward()#一个batch做一次反向传播

                tr_loss += loss.item()

                if (step + 1) % args.gradient_accumulation_steps == 0:
                    if args.fp16:
                        # modify learning rate with special warm up BERT uses
                        # if args.fp16 is False, BertAdam is used that handles this automatically
                        lr_this_step = args.learning_rate * warmup_linear.get_lr(
                            global_step / num_train_optimization_steps,
                            args.warmup_proportion)
                        for param_group in optimizer.param_groups:
                            param_group['lr'] = lr_this_step
                    optimizer.step()
                    optimizer.zero_grad()
                    global_step += 1


            data_count = (step+1)*args.train_batch_size
            tr_loss = tr_loss / data_count

            model.eval()

            eval_loss = 0  # 测试数据的损失
            nb_eval_steps = 0  # 测试用例数
            for input_ids, input_mask, segment_ids, label_ids in tqdm(eval_dataloader, desc="testing"):
                input_ids = input_ids.cuda()
                input_mask = input_mask.cuda()
                segment_ids = segment_ids.cuda()
                label_ids = label_ids.cuda()

                with torch.no_grad():
                    logits = model(input_ids, segment_ids, input_mask, labels=None)

                if output_mode == "classification":
                    loss_fct = CrossEntropyLoss()
                    tmp_eval_loss = loss_fct(logits.view(-1, num_labels), label_ids.view(-1))
                elif output_mode == "regression":
                    loss_fct = MSELoss()
                    tmp_eval_loss = loss_fct(logits.view(-1), label_ids.view(-1))

                eval_loss += tmp_eval_loss.mean().item()
                nb_eval_steps += 1

                if len(preds) == 0:
                    preds.append(logits.detach().cpu().numpy())
                else:
                    preds[0] = np.append(
                        preds[0], logits.detach().cpu().numpy(), axis=0)
            loss_test.append(eval_loss / nb_eval_steps)

            preds = preds[0]
            if output_mode == "classification":
                preds = np.argmax(preds, axis=1)
            elif output_mode == "regression":
                preds = np.squeeze(preds)
            test_result = compute_metrics(task_name, preds, test_label_ids.numpy())
            preds = []  # 本epoch清空预测值

            #打印错误的数据
            # print_err(preds,test_label_ids.numpy(),test_both_answers,epoch)


            valid_loss = 0  # 损失
            nb_valid_steps = 0  # 例数
            for input_ids, input_mask, segment_ids, label_ids in tqdm(valid_dataloader, desc="validating"):
                input_ids = input_ids.cuda()
                input_mask = input_mask.cuda()
                segment_ids = segment_ids.cuda()
                label_ids = label_ids.cuda()

                with torch.no_grad():
                    logits = model(input_ids, segment_ids, input_mask, labels=None)

                if output_mode == "classification":
                    loss_fct = CrossEntropyLoss()
                    tmp_valid_loss = loss_fct(logits.view(-1, num_labels), label_ids.view(-1))
                elif output_mode == "regression":
                    loss_fct = MSELoss()
                    tmp_valid_loss = loss_fct(logits.view(-1), label_ids.view(-1))

                valid_loss += tmp_valid_loss.mean().item()
                nb_valid_steps += 1

                # 得到预测值
                if len(valid_preds) == 0:
                    valid_preds.append(logits.detach().cpu().numpy())
                else:
                    valid_preds[0] = np.append(
                        valid_preds[0], logits.detach().cpu().numpy(), axis=0)

            loss_valid.append(valid_loss / nb_valid_steps)

            valid_preds = valid_preds[0]
            if output_mode == "classification":
                valid_preds = np.argmax(valid_preds, axis=1)
            elif output_mode == "regression":
                valid_preds = np.squeeze(valid_preds)

            valid_result = compute_metrics(task_name, valid_preds, valid_label_ids.numpy())
            valid_preds = []  # 本epoch清空预测值

            print("本轮train的loss:", tr_loss)
            print("test_result:", test_result)
            print("test_loss:", loss_test)
            train_loss.append(tr_loss)
            d = test_result["acc"]
            test_acc.append(d["acc"])
            test_mf1.append(d["m_f1"])
            test_wf1.append(d["w_f1"])
            d = valid_result["acc"]
            valid_acc.append(d["acc"])
            valid_mf1.append(d["m_f1"])
            valid_wf1.append(d["w_f1"])

        output_eval_file = os.path.join(args.output_dir, "results.txt")
        with open(output_eval_file, "a+") as writer:
            writer.write('\n')
            writer.write("test acc:%s\n" % str(test_acc))
            writer.write("test wf1:%s\n" % str(test_wf1))
            writer.write("test mf1:%s\n" % str(test_mf1))
            writer.write("valid acc:%s\n" % str(valid_acc))
            writer.write("valid wf1:%s\n" % str(valid_wf1))
            writer.write("valid mf1:%s\n" % str(valid_mf1))
            writer.write("train loss:%s\n" % str(train_loss))
            writer.write("test loss:%s\n" % str(loss_test))


if __name__ == "__main__":
    main()
