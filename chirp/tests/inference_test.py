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

"""Tests for inference library."""

import os
import tempfile

import apache_beam as beam
from apache_beam.testing import test_pipeline
from chirp import path_utils
from chirp.inference import embed_lib
from chirp.inference import models
from chirp.inference import tf_examples
from chirp.taxonomy import namespace_db
from ml_collections import config_dict
import numpy as np
import tensorflow as tf

from absl.testing import absltest
from absl.testing import parameterized


class InferenceTest(parameterized.TestCase):

  @parameterized.product(
      make_embeddings=(True, False),
      make_logits=(True, False),
      make_separated_audio=(True, False),
      write_embeddings=(True, False),
      write_logits=(True, False),
      write_separated_audio=(True, False),
      write_raw_audio=(True, False),
  )
  def test_embed_fn(
      self,
      make_embeddings,
      make_logits,
      make_separated_audio,
      write_embeddings,
      write_logits,
      write_raw_audio,
      write_separated_audio,
  ):
    model_kwargs = {
        'sample_rate': 16000,
        'embedding_size': 128,
        'make_embeddings': make_embeddings,
        'make_logits': make_logits,
        'make_separated_audio': make_separated_audio,
    }
    embed_fn = embed_lib.EmbedFn(
        write_embeddings=write_embeddings,
        write_logits=write_logits,
        write_separated_audio=write_separated_audio,
        write_raw_audio=write_raw_audio,
        model_key='placeholder_model',
        model_config=model_kwargs,
    )
    embed_fn.setup()
    self.assertIsNotNone(embed_fn.embedding_model)

    test_wav_path = path_utils.get_absolute_epath(
        'tests/testdata/tfds_builder_wav_directory_test/clap.wav'
    )

    source_info = embed_lib.SourceInfo(test_wav_path, 0, 1)
    example = embed_fn.process(source_info, crop_s=10.0)[0]
    serialized = example.SerializeToString()

    parser = tf_examples.get_example_parser(logit_names=['label'])
    got_example = parser(serialized)
    self.assertIsNotNone(got_example)
    self.assertEqual(got_example[tf_examples.FILE_NAME], 'clap.wav')
    if make_embeddings and write_embeddings:
      embedding = got_example[tf_examples.EMBEDDING]
      self.assertSequenceEqual(
          embedding.shape, got_example[tf_examples.EMBEDDING_SHAPE]
      )
    else:
      self.assertEqual(got_example[tf_examples.EMBEDDING].shape, (0,))

    if make_logits and write_logits:
      self.assertSequenceEqual(
          got_example['label'].shape, got_example['label_shape']
      )
    else:
      self.assertEqual(got_example['label'].shape, (0,))

    if make_separated_audio and write_separated_audio:
      separated_audio = got_example[tf_examples.SEPARATED_AUDIO]
      self.assertSequenceEqual(
          separated_audio.shape, got_example[tf_examples.SEPARATED_AUDIO_SHAPE]
      )
    else:
      self.assertEqual(got_example[tf_examples.SEPARATED_AUDIO].shape, (0,))

    if write_raw_audio:
      raw_audio = got_example[tf_examples.RAW_AUDIO]
      self.assertSequenceEqual(
          raw_audio.shape, got_example[tf_examples.RAW_AUDIO_SHAPE]
      )
    else:
      self.assertEqual(got_example[tf_examples.RAW_AUDIO].shape, (0,))

  def test_sep_embed_wrapper(self):
    """Check that the joint-model wrapper works as intended."""
    separator = models.PlaceholderModel(
        sample_rate=22050,
        make_embeddings=False,
        make_logits=False,
        make_separated_audio=True,
    )
    db = namespace_db.load_db()
    target_class_list = db.class_lists['high_sierras']

    embeddor = models.PlaceholderModel(
        sample_rate=22050,
        make_embeddings=True,
        make_logits=True,
        make_separated_audio=False,
        target_class_list=target_class_list,
    )
    fake_config = config_dict.ConfigDict()
    sep_embed = models.SeparateEmbedModel(
        sample_rate=22050,
        taxonomy_model_tf_config=fake_config,
        separator_model_tf_config=fake_config,
        separation_model=separator,
        embedding_model=embeddor,
    )
    audio = np.zeros(5 * 22050, np.float32)

    outputs = sep_embed.embed(audio)
    # The PlaceholderModel produces one embedding per second, and we have
    # five seconds of audio, with two separated channels, plus the channel
    # for the raw audio.
    # Note that this checks that the sample-rate conversion between the
    # separation model and embedding model has worked correctly.
    self.assertSequenceEqual(
        outputs.embeddings.shape, [5, 3, embeddor.embedding_size]
    )
    # The Sep+Embed model takes the max logits over the channel dimension.
    self.assertSequenceEqual(
        outputs.logits['label'].shape, [5, target_class_list.size]
    )

  def test_beam_pipeline(self):
    """Check that we can write embeddings to TFRecord file."""
    test_wav_path = path_utils.get_absolute_epath(
        'tests/testdata/tfds_builder_wav_directory_test/clap.wav'
    )
    source_infos = [embed_lib.SourceInfo(test_wav_path.as_posix(), 0, 0)]
    base_pipeline = test_pipeline.TestPipeline()
    tempdir = tempfile.gettempdir()
    output_dir = os.path.join(tempdir, 'testBeamStuff_output')

    model_kwargs = {
        'sample_rate': 16000,
        'embedding_size': 128,
        'make_embeddings': True,
        'make_logits': False,
        'make_separated_audio': False,
    }
    embed_fn = embed_lib.EmbedFn(
        write_embeddings=False,
        write_logits=False,
        write_separated_audio=False,
        write_raw_audio=False,
        model_key='placeholder_model',
        model_config=model_kwargs,
    )

    metrics = embed_lib.build_run_pipeline(
        base_pipeline, output_dir, source_infos, embed_fn
    )
    counter = counter = metrics.query(
        beam.metrics.MetricsFilter().with_name('examples_processed')
    )['counters']
    self.assertEqual(counter[0].result, 1)

    print(metrics)


if __name__ == '__main__':
  absltest.main()
