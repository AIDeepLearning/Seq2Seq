#!/usr/bin/env bash
cd ../..
python3 inference.py\
    --beam_width 1\
    --inference_batch_size 256\
    --model_path checkpoints/lcsts_split_pointer_generator_coverage/lcsts.ckpt-734000\
    --inference_input dataset/lcsts/split/sources.test.txt\
    --inference_output dataset/lcsts/split/summaries.inference.coverage.734000.txt\
    --extend_vocabs True