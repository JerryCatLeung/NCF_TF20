# Copyright 2018 The TensorFlow Authors. All Rights Reserved.
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
# ==============================================================================
"""Common functionalities used by both Keras and Estimator implementations.
"""

import json
import logging
import os

# pylint: disable=g-bad-import-order
import numpy as np
from absl import flags
import tensorflow as tf
# pylint: enable=g-bad-import-order

import movielens
import constants as rconst
import data_pipeline
import data_preprocessing
from flags import core as flags_core


FLAGS = flags.FLAGS


def get_inputs(params):
  """Returns some parameters used by the model."""
  if FLAGS.download_if_missing:
    movielens.download(FLAGS.dataset, FLAGS.data_dir)

  if FLAGS.seed is not None:
    np.random.seed(FLAGS.seed)


  num_users, num_items, producer = data_preprocessing.instantiate_pipeline(
        dataset=FLAGS.dataset, data_dir=FLAGS.data_dir, params=params,
        constructor_type=FLAGS.constructor_type,
        deterministic=FLAGS.seed is not None)

  num_train_steps = (producer.train_batches_per_epoch //
                       params["batches_per_step"])
  num_eval_steps = (producer.eval_batches_per_epoch //
                      params["batches_per_step"])
  assert not producer.train_batches_per_epoch % params["batches_per_step"]
  assert not producer.eval_batches_per_epoch % params["batches_per_step"]

  return num_users, num_items, num_train_steps, num_eval_steps, producer


def parse_flags(flags_obj):
  """Convenience function to turn flags into params."""
  num_gpus = 1
  num_devices = 1

  batch_size = (flags_obj.batch_size + num_devices - 1) // num_devices

  eval_divisor = (rconst.NUM_EVAL_NEGATIVES + 1) * num_devices
  eval_batch_size = flags_obj.eval_batch_size or flags_obj.batch_size
  eval_batch_size = ((eval_batch_size + eval_divisor - 1) //
                     eval_divisor * eval_divisor // num_devices)

  return {
      "train_epochs": flags_obj.train_epochs,
      "batches_per_step": num_devices,
      "use_seed": flags_obj.seed is not None,
      "batch_size": batch_size,
      "eval_batch_size": eval_batch_size,
      "learning_rate": flags_obj.learning_rate,
      "mf_dim": flags_obj.num_factors,
      "model_layers": [int(layer) for layer in flags_obj.layers],
      "mf_regularization": flags_obj.mf_regularization,
      "mlp_reg_layers": [float(reg) for reg in flags_obj.mlp_regularization],
      "num_neg": flags_obj.num_neg,
      "beta1": flags_obj.beta1,
      "beta2": flags_obj.beta2,
      "epsilon": flags_obj.epsilon,
      "epochs_between_evals": FLAGS.epochs_between_evals
  }


def get_optimizer(params):
  optimizer = tf.keras.optimizers.Adam(
      learning_rate=params["learning_rate"],
      beta_1=params["beta1"],
      beta_2=params["beta2"],
      epsilon=params["epsilon"])

  return optimizer


def define_ncf_flags():
  """Add flags for running ncf_main."""
  # Add common flags
  flags_core.define_base(export_dir=False)

  flags_core.define_benchmark()

  flags.adopt_module_key_flags(flags_core)

  flags_core.set_defaults(
      model_dir="./ncf/",
      data_dir="./movielens-data/",
      train_epochs=2,
      batch_size=1000
  )

  # Add ncf-specific flags
  flags.DEFINE_enum(
      name="dataset", default="ml-20m",
      enum_values=["ml-1m", "ml-20m"], case_sensitive=False,
      help=flags_core.help_wrap(
          "Dataset to be trained and evaluated."))

  flags.DEFINE_boolean(
      name="download_if_missing", default=True, help=flags_core.help_wrap(
          "Download data to data_dir if it is not already present."))

  flags.DEFINE_integer(
      name="eval_batch_size", default=None, help=flags_core.help_wrap(
          "The batch size used for evaluation. This should generally be larger"
          "than the training batch size as the lack of back propagation during"
          "evaluation can allow for larger batch sizes to fit in memory. If not"
          "specified, the training batch size (--batch_size) will be used."))

  flags.DEFINE_integer(
      name="num_factors", default=8,
      help=flags_core.help_wrap("The Embedding size of MF model."))

  # Set the default as a list of strings to be consistent with input arguments
  flags.DEFINE_list(
      name="layers", default=["64", "32", "16", "8"],
      help=flags_core.help_wrap(
          "The sizes of hidden layers for MLP. Example "
          "to specify different sizes of MLP layers: --layers=32,16,8,4"))

  flags.DEFINE_float(
      name="mf_regularization", default=0.,
      help=flags_core.help_wrap(
          "The regularization factor for MF embeddings. The factor is used by "
          "regularizer which allows to apply penalties on layer parameters or "
          "layer activity during optimization."))

  flags.DEFINE_list(
      name="mlp_regularization", default=["0.", "0.", "0.", "0."],
      help=flags_core.help_wrap(
          "The regularization factor for each MLP layer. See mf_regularization "
          "help for more info about regularization factor."))

  flags.DEFINE_integer(
      name="num_neg", default=4,
      help=flags_core.help_wrap(
          "The Number of negative instances to pair with a positive instance."))

  flags.DEFINE_float(
      name="learning_rate", default=0.001,
      help=flags_core.help_wrap("The learning rate."))

  flags.DEFINE_float(
      name="beta1", default=0.9,
      help=flags_core.help_wrap("beta1 hyperparameter for the Adam optimizer."))

  flags.DEFINE_float(
      name="beta2", default=0.999,
      help=flags_core.help_wrap("beta2 hyperparameter for the Adam optimizer."))

  flags.DEFINE_float(
      name="epsilon", default=1e-8,
      help=flags_core.help_wrap("epsilon hyperparameter for the Adam "
                                "optimizer."))

  flags.DEFINE_float(
      name="hr_threshold", default=None,
      help=flags_core.help_wrap(
          "If passed, training will stop when the evaluation metric HR is "
          "greater than or equal to hr_threshold. For dataset ml-1m, the "
          "desired hr_threshold is 0.68 which is the result from the paper; "
          "For dataset ml-20m, the threshold can be set as 0.95 which is "
          "achieved by MLPerf implementation."))

  flags.DEFINE_enum(
      name="constructor_type", default="bisection",
      enum_values=["bisection", "materialized"], case_sensitive=False,
      help=flags_core.help_wrap(
          "Strategy to use for generating false negatives. materialized has a"
          "precompute that scales badly, but a faster per-epoch construction"
          "time and can be faster on very large systems."))

  flags.DEFINE_integer(
      name="seed", default=None, help=flags_core.help_wrap(
          "This value will be used to seed both NumPy and TensorFlow."))


  @flags.validator("eval_batch_size", "eval_batch_size must be at least {}"
                   .format(rconst.NUM_EVAL_NEGATIVES + 1))
  def eval_size_check(eval_batch_size):
    return (eval_batch_size is None or
            int(eval_batch_size) > rconst.NUM_EVAL_NEGATIVES)