# Third-party notices

This repository is licensed Apache-2.0 ([`LICENSE`](LICENSE)). It builds on
third-party datasets and
libraries with their own terms. **No third-party dataset is redistributed
here** — `bench-quality/data/` is gitignored and every dataset is fetched by
the download commands in `bench-quality/README.md` directly from its source.

## Benchmark datasets (downloaded, not redistributed)

| dataset | source | license | note |
|---|---|---|---|
| LongMemEval (cleaned) | [xiaowu0162/longmemeval-cleaned](https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned) | MIT | |
| LoCoMo | [snap-research/locomo](https://github.com/snap-research/locomo) | **CC BY-NC 4.0** | non-commercial — results here are research benchmarking; check your own use |
| BEAM (128K tier) | [mohammadtavakoli78/BEAM](https://github.com/mohammadtavakoli78/BEAM) | CC BY-SA 4.0 (data), MIT (code) | evidence annotations are model-generated + human-reviewed (disclosed in README) |
| SWE-Bench-CL | [thomasjoshi/agents-never-forget](https://github.com/thomasjoshi/agents-never-forget) | MIT | derived from SWE-bench Verified (princeton-nlp) |
| ABCD | [asappresearch/abcd](https://github.com/asappresearch/abcd) | MIT | Chen et al., NAACL 2021 |
| STAR | [RasaHQ/STAR](https://github.com/RasaHQ/STAR) | MIT | Mosig et al. 2020; authored task flowcharts |
| MultiDoc2Dial | [IBM, doc2dial.github.io](https://doc2dial.github.io/multidoc2dial/) | CC BY 3.0 | Feng et al., EMNLP 2021 |
| FloDial | [dair-iitd/FloDial](https://dair-iitd.github.io/FloDial/) | CDLA-Sharing-1.0 | Raghu et al., EMNLP 2021 |
| Terminal-Bench 2.0 trajectories | [yoonholee/terminalbench-trajectories](https://huggingface.co/datasets/yoonholee/terminalbench-trajectories) | Apache-2.0 | tbench.ai leaderboard runs; 52,104 test-verified trials over 89 tasks |

Live-A/B experiments (`bench-quality/live-ab/`) clone pytest-dev/pytest (MIT)
and sphinx-doc/sphinx (BSD-2-Clause) at historical commits; clones are
gitignored and never redistributed.

## Key libraries and models

- [sqlite-loadable](https://github.com/asg017/sqlite-loadable-rs) (MIT/Apache-2.0) —
  the Rust extension framework; pinned `=0.0.6-alpha.6`.
- [sqlite-vec](https://github.com/asg017/sqlite-vec) (MIT/Apache-2.0) —
  vector search used in the MCP server and README examples.
- [sentence-transformers](https://sbert.net) (Apache-2.0) and models:
  `all-MiniLM-L6-v2` (Apache-2.0), `Qwen/Qwen3-Embedding-0.6B` (Apache-2.0),
  `BAAI/bge-m3` (MIT) — downloaded from Hugging Face at run time.
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) (MIT).

## Scientific sources

The scoring math implements published equations, cited in code comments:
ACT-R base-level learning (Anderson & Lebiere 1998), the Petrov (2006)
incremental approximation, and standard EWMA. The Generative Agents
comparison condition implements the scoring formula of Park et al. (2023).
