# coding=utf-8
# Copyright 2022 The Chirp Authors.
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

"""Configuration to run baseline model."""
from chirp import config_utils
from ml_collections import config_dict

_c = config_utils.callable_config


def get_config() -> config_dict.ConfigDict:
  """Create configuration dictionary for training."""
  sample_rate_hz = config_dict.FieldReference(32_000)
  batch_size = config_dict.FieldReference(64)

  config = config_dict.ConfigDict()
  config.sample_rate_hz = sample_rate_hz
  config.batch_size = batch_size

  # Configure the data
  window_size_s = config_dict.FieldReference(5)

  train_dataset_config = config_dict.ConfigDict()
  train_dataset_config.pipeline = _c(
      "pipeline.Pipeline",
      ops=[
          _c("pipeline.OnlyJaxTypes"),
          _c("pipeline.MultiHot"),
          _c("pipeline.MixAudio", mixin_prob=0.75),
          _c("pipeline.Batch", batch_size=batch_size,
             split_across_devices=True),
          _c("pipeline.RandomSlice", window_size=window_size_s),
          _c("pipeline.RandomNormalizeAudio", min_gain=0.15, max_gain=0.25),
      ])
  train_dataset_config.split = "train"
  config.train_dataset_config = train_dataset_config

  eval_dataset_config = config_dict.ConfigDict()
  eval_dataset_config.pipeline = _c(
      "pipeline.Pipeline",
      ops=[
          _c("pipeline.OnlyJaxTypes"),
          _c("pipeline.MultiHot"),
          _c("pipeline.Batch", batch_size=batch_size,
             split_across_devices=True),
          _c("pipeline.Slice", window_size=window_size_s, start=0.5),
          _c("pipeline.NormalizeAudio", target_gain=0.2),
      ])
  eval_dataset_config.split = "train"
  config.eval_dataset_config = eval_dataset_config

  # Configure the experiment setup
  init_config = config_dict.ConfigDict()
  init_config.learning_rate = 0.0001
  init_config.input_size = window_size_s * sample_rate_hz
  init_config.rng_seed = 0
  config.init_config = init_config

  model_config = config_dict.ConfigDict()
  model_config.encoder = _c(
      "efficientnet.EfficientNet",
      model=_c("efficientnet.EfficientNetModel", value="b1"))
  model_config.taxonomy_loss_weight = 0.25
  init_config.model_config = model_config

  model_config.frontend = _c(
      "frontend.MorletWaveletTransform",
      features=160,
      stride=sample_rate_hz // 100,
      kernel_size=2_048,  # ~0.08 * 32,000
      sample_rate=sample_rate_hz,
      freq_range=(60, 10_000),
      scaling_config=_c("frontend.PCENScalingConfig"))

  # Configure the training loop
  num_train_steps = config_dict.FieldReference(250_000)

  train_config = config_dict.ConfigDict()
  train_config.num_train_steps = num_train_steps
  train_config.log_every_steps = 250
  train_config.checkpoint_every_steps = 5_000
  config.train_config = train_config

  eval_config = config_dict.ConfigDict()
  eval_config.num_train_steps = num_train_steps
  config.eval_config = eval_config

  return config
