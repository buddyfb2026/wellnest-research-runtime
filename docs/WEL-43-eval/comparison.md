# WEL-43 baseline vs challenger — one adjustment

Adjustment: **sentence integrity over already-extracted text**. Baseline `rules_incumbent` (unchanged default) vs challenger `sentence_integrity_v1`.

Budget consumed: **0 model calls, 0 network requests**.

## Frozen manifest

| file | sha256 |
|---|---|
| eval/wel43/dev_cases.json | `8532e6371eae908707140baeb353035fc83d7f7aed8054e071ede276583ade4f` |
| eval/wel43/rubric.md | `c0d6b70ccc0fb1ce04bc1baf06f101b90c0dd6fa2c2d1cdc7c33bdf1f6cfa308` |
| research/evaluate.py | `590fd554219b403ed421c63d967d2148be3b2f3680dbf9bb4e7cf971349b6811` |
| research/rules.py | `876449c08c2df0ba172123eae5b608cb9c6a3be3cbb15067652edfcbd971ce93` |
| research/sentence_integrity.py | `0f062c3b0bef50cea91655301008fe70b3dc1052527a68f9f112b17b9fd79ba9` |

## Development cases (labeled, used to design the adjustment)

| case | truth: sentence present | baseline | challenger | note |
|---|---|---|---|---|
| clean_whole_sentence | yes | match | match | Both reviewed sentences appear as complete sentences on their own lines. |
| split_by_block_break | yes | no match | match | One sentence interrupted by an inline block tag arrives as two lines; a reader still sees one whole sentence. |
| nbsp_and_zero_width | yes | no match | match | The same sentence carrying a non-breaking space and a zero-width space; visually identical to a reader. |
| fragment_only | no | no match | no match | Only the tail fragment is present, not the reviewed whole sentence. |
| negated_prefix | no | no match | no match | A prefix changes the meaning, so the reviewed support sentence is not present. The problem sentence is present in the text, but the registry only looks for it once a support sentence matched, so no variant reports it here. |
| question_form | no | no match | no match | Question form is a different sentence and must not match. |
| heading_then_sentence | yes | match | match | A terminator-less heading precedes the reviewed sentence; rejoining must not swallow it. |
| injected_instructions | yes | match | match | Injection text must stay detectable by extract.scan_for_instructions and must not change matching. |
| duplicated_page | yes | match | match | The same page text twice yields one match, not two. |
| unrelated_document | no | no match | no match | No reviewed sentence is present; both variants must find nothing. |
| false_join_bait | no | no match | no match | Two unrelated lines that a careless rejoin could fuse; no reviewed sentence exists here, so any match is a false support. |

Agreement with ground truth: baseline 9/11, challenger 11/11. New true matches 4, new false matches 0, lost matches 0.

## Holdout (unseen documents, read after the manifest was frozen)

Corpus: 8 stored documents of already-extracted text. Claims are limited to sentence processing; HTML extraction is NOT TESTED here.

| evidence | url | chars | baseline match | challenger match |
|---|---|---|---|---|
| 1 | https://www.goodhousekeeping.com/home/cleaning/a37462/how-often-you-should-clean-everything/ | 6810 | no | no |
| 2 | https://www.goodhousekeeping.com/home/cleaning/a71856702/how-to-clean-air-fryer-basket/ | 4500 | yes | yes |
| 3 | https://www.goodhousekeeping.com/home/cleaning/a71604725/why-robot-vacuum-missing-spots/ | 5227 | no | no |
| 4 | https://www.goodhousekeeping.com/home/cleaning/a73289957/what-happens-when-you-use-too-much-detergent/ | 5155 | no | no |
| 5 | https://www.goodhousekeeping.com/home/cleaning/a73289971/things-to-always-wash-in-cold-water/ | 4616 | no | no |
| 6 | https://www.goodhousekeeping.com/home/cleaning/a73289984/things-to-wash-before-using/ | 4728 | no | no |
| 7 | https://www.goodhousekeeping.com/home/cleaning/a73377343/laundry-pros-explain-unshrinking-trick/ | 4464 | no | no |
| 8 | https://www.goodhousekeeping.com/home/cleaning/a73436915/how-to-clean-white-converse-sneakers/ | 5396 | no | no |

Documents with a registry match: baseline 1, challenger 1. Documents where the two variants differ: 0.


## Verdict: ADOPT-WITH-REVIEW

- blockers: none
- A verdict is a recommendation to a human reviewer. The default stays research/rules.py in every case; nothing is adopted or activated automatically.
