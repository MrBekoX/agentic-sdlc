# Commit history map

On 2026-10-12 this repository was published with a rewritten history: personal e-mail addresses in
commit metadata became the GitHub noreply address, `Claude-Session:` trailer lines were removed from
commit messages, and `audit-docs/` was removed from every commit. Authors, dates, subjects and order
are unchanged; 279 of the 286 commits have byte-identical trees, and the other 7 differ only by the
removed `audit-docs/` file. The original history is kept in the private archive repository.

Evidence recorded before 2026-10-12 (the release ledgers, the compatibility matrix and the
publication notes) names commits by their original ids. This table maps each original id to the
id of the same commit in this repository; `tests/test_release_ledger_docs.py` resolves carried
ledger commits through it.

| Original commit | Public commit | Date | Subject |
|---|---|---|---|
| fc0dff0186b0628a561929fee98c5178c0bc9fb3 | 8c81ed5786c74cacd4e07bd18ad4c78c62a919c0 | 2026-10-12 | Restore the CI push and pull_request triggers (#76) |
| a95fc8c9017a485bc8fe0d3c6ce7e098e12225b2 | c34416e52d3f711ddb7add1b297e485900e6a646 | 2026-10-12 | Record the earlier live runs as carried results in the 0.5.0 ledger (#77) |
| f5ba8e9a33d6f53b187d838b530e850f1d5eaa3c | 0fb0d5297bdaf8d4eb0e3c94b5c932f663ccafa4 | 2026-10-12 | Record the measurements of 36ba3f6 in the 0.5.0 ledger |
| 36ba3f6029602e88d9f4efd2c209a62a923716d4 | 8025b38b42ec6572d9c73daf60f75ba8069900b9 | 2026-10-12 | Decode the shallow-repository probe as UTF-8 in the ledger tests |
| 8e907f474546bbb42021cb4b82aff83f9b4fbd1c | 8986d1b1202816c8a35bf885a2c592f8f3dbb3e0 | 2026-10-12 | Check carried ledger states against their sources |
| 12d035544d0da00978ac593f1569b0b58ad8cdfb | d2214c52e417b39ae7fcb49d4bd286b211f35c2d | 2026-10-12 | Use a canonical temp path in the marketplace preparation tests |
| ef6d660d38b57c08190baa66e6732ebec243682c | d98aa678f921d1c998fe3b154dd44769462a834f | 2026-10-12 | Record the carried-results commit's measurements in the ledger |
| 44321c5d3ac808b21b6fb1fc9fe07839ae0889f0 | f6d6c45f98cf0a70d9dba6858b0a6563dedcc976 | 2026-10-12 | Record the earlier live runs as carried results in the 0.5.0 ledger |
| 0684d546adeaf5f8dca4bb37985427f45c11888d | f900761c3a31d4ce79040b90461a23d300585478 | 2026-10-12 | Restore the CI push and pull_request triggers |
| 3d02f7fde55d9963570d06cb425e2e257e78b729 | 8d691feb4eb879c39aea7e7937935a7af87f4784 | 2026-10-12 | Release 0.5.0: version bump and release evidence ledger (#75) |
| bc61d8ffb2b1d0eb67392be4ae90c2a32badd991 | 193dd49b20aaa2ff520401258d454f91ccc38603 | 2026-10-12 | Record the 0.5.0 release-commit measurements in the ledger |
| faa303fb92e00bac776a2a72b9d387d23bbcfd1d | 8e43e27f76731959032376227c3bcc184047fb17 | 2026-10-12 | Fix the 0.5.0 bump fallout and tighten the ledger's carry rule |
| d0b4c206876e8782c1a8ce47f7142fd01d7ed7aa | b3569badbe49f1e292fbc4747b2ce7f686f197c6 | 2026-10-12 | Release 0.5.0: bump the version and add its release evidence ledger |
| 6bd7b68b8937aafb70ad83978c911d95285b2bb6 | 0cd9c4eec7b0b6f86e075dc675b494f445f6b67c | 2026-10-12 | Correct install guidance and publication docs before release (#74) |
| beaba0f357207bca0dfdde08bd50f14563b5b8eb | 40a8e126d7ae844150445033d1324864906e1703 | 2026-10-12 | Rebind the compatibility matrix to main after the ZCode hook change (#73) |
| 1a9ac73b47f4f618e1f62c7d6331a47c097a2898 | eeb1a86d3fbfd1a31e320324f54834c1e3099863 | 2026-10-12 | docs: list Kimi Code as its own experimental adapter in release readiness (#58) |
| f3124cf1aeb574d6737ad79a09b5d9b53cbfa779 | 8c7894f4ee93fe21c0370fd7153bcc2ea310d95b | 2026-10-12 | fix: emit only documented hook-output keys on ZCode marketplace installs (#59) |
| cac9762343979769db0b6a107c459d8077586098 | e1275523e10b3a683b8dd27fd46c863ea1763189 | 2026-10-12 | Record ZCode native evidence on Linux (#72) |
| df3cd913308e2328f62c4713bd2272b87f932f06 | f58230ba4cfc52f53aefa9e69352fad40c7247f2 | 2026-10-12 | Add a manual ZCode native lifecycle job on Linux (#71) |
| 8d4c3b69554dc1333f2fd90f985a244297c7b281 | 07a99924277844287a26ed6636503b0ba47c5107 | 2026-10-12 | Record ZCode native evidence on macOS (#70) |
| 64d6744a0148f6e3d190d297b890c8698c80df39 | 222c05c8d6c13cf9b93846e543da4bae7aba2e37 | 2026-10-12 | Run the ZCode native lifecycle on the macOS runner (#69) |
| 56e29854acb9f16ebd0a790ff7a86f9f9863fbb0 | c65d717895dc105bf942d28dfe72533ec83fc6b8 | 2026-10-12 | Record macOS native evidence for Claude Code, Codex, Kimi and Grok (#68) |
| 9bc884b3936a6ca823d72191f53a25c38115313a | a3c785418a17fbec1dccc56091603d0c7a427631 | 2026-10-12 | Add a manual macOS native lifecycle job and record ZCode evidence (#67) |
| 86625717bf045cccf3d91050092a0a9928685604 | 5e797ec86cb498799bc57205a684dddd05aab978 | 2026-10-12 | ci: bump actions/setup-node from 7.0.0 to 7.1.0 (#63) |
| dc6ebff42a4e4375c16efe7b618df85a673b8c8c | 68b1608c46488294260c3d2e2be9aa8054ca89be | 2026-10-12 | Record Linux native evidence for Grok and Kimi (#66) |
| 02b6e21cfd90d8bea54914baac81dafce5e8dd6d | f2b2423a61284628170b72d322a7c899227ab8f3 | 2026-10-12 | Make agentic-sdlc installable on all five platforms without machine-specific setup (#65) |
| 6f38e2a49f1225af0982fb8ffa688188239217db | c4654c1f48c9875c4a14748472a5c5235724c79e | 2026-10-12 | Prepare marketplace packets and native verification (#64) |
| 3bcbf7b9b4ae7688c8017756086f9128240b64f3 | d15ceae7a3cfe158f1f7502bfaef2769459b4d49 | 2026-10-11 | fix: verify portable plugin distribution lifecycle (#62) |
| d7cf7231813d4df1bd78083cce3b17bbd9b6d4c9 | 75804268069ef5bf332909c90b6429e0af2741c1 | 2026-10-10 | fix: make multi-platform plugin distribution portable (#61) |
| f4e8684f9de1251bf1b1fb6952524cc04f3dedff | 3661cafa5b3170365c49ea26062826d18b31bcbb | 2026-10-10 | fix(codex): make marketplace hooks portable (#60) |
| c80a4dd33f4321dc6471985c27485b85da4b7588 | 0a181dce3f44a751dd606a5f6dc01d88d2f78591 | 2026-10-08 | Merge pull request #57 from MrBekoX/fix/claude-code-runtime-currency |
| 899da60583f0616ced764ac184c5b06b9e4b76e6 | 0a432ef8244ea2283e49fb1a37a4b98b1b0467dc | 2026-10-08 | Merge origin/main into fix/claude-code-runtime-currency |
| 01d2932f5140efc87185e1df91b32f90b5825d7a | 151ab2590374979204d55bbb4bbcb568a5e89a25 | 2026-10-08 | fix: align Claude-only runtime behavior with Claude Code 2.1.293 |
| 3056642833e591dbd2fb9ef90db278c986af5f13 | 38ce1fed54a07ea66edd2aafda30185081dbc412 | 2026-10-07 | Merge pull request #56 from MrBekoX/codex/codex-marketplace-readiness |
| aaad389b984b4fba74ac0d06d4113297adaaa04a | cdef59552fa7d733b8c5109db144ec3c0a66e515 | 2026-10-07 | fix: prepare self-contained Codex public plugin packages |
| 3e34675f73efd1884034f16cf6cae98a09afca84 | 80eb4308dd50cdeb1edb71a359180b6daf8496d9 | 2026-09-21 | Merge pull request #55 from MrBekoX/fix/ci-trigger-tests-accept-bypass |
| 7a2120847c4343d0c22615f20cf2278971bbffd6 | d7d12cd979766b3a0e2c7e21972e8fc82788815c | 2026-09-21 | test(ci): accept the documented bypass without dropping the trigger guard |
| d595621c7e1cb389423774086e18f74c15b7c20a | d1075ff1c7407b9f95860a7266493c4a7d9fbb30 | 2026-09-21 | ci: finish the action bumps the new job left behind |
| a8dfe14a4e62ccc03dc4f76e15420798bfb76cb7 | fda9865244574a45e75e2edcb50fbe544ba00943 | 2026-09-21 | Merge remote-tracking branch 'origin/dependabot/github_actions/actions/setup-python-7.0.0' |
| 6943e580d3bae7dcded47efcf666d5edcc3dd329 | 5d0e042470cafd5f11979c10113aa1072646336f | 2026-09-21 | Merge remote-tracking branch 'origin/dependabot/github_actions/actions/setup-node-7.0.0' |
| 8ab399cdd94dd7e6cede573e697c5b108a96835e | 9be58ca7b9052be0664eef8b0a050151e9988066 | 2026-09-21 | Merge remote-tracking branch 'origin/dependabot/github_actions/actions/checkout-7.0.1' |
| 5e96671f34cc8bb4bfa83ecd9d2dad5a05c04eeb | 613aa72dc07be045ff41d098f5ad6a3fd6b37684 | 2026-09-21 | Merge pull request #41 from MrBekoX/ci/phase2-validate-and-manifest-coverage |
| ec942306e32c9a4ac5e04c98f742ec2256462585 | dd1504368c455e4c642b2d8d1b0c597784f178a0 | 2026-09-21 | Merge remote-tracking branch 'origin/main' into ci/phase2-validate-and-manifest-coverage |
| 6619d9dab5c62572567193aca1b7d04aa0d5abee | 823377b9d33befefb0c949ee506022a8cbdfc8bd | 2026-09-21 | Merge pull request #54 from MrBekoX/ci/bypass-until-billing-fixed |
| 886e1526cb0a84bf9db9bcfc206cb423dee79328 | 0ddea49d3d0f1d383509ec4f0a7a6abada873a85 | 2026-09-21 | ci: run on manual dispatch only, until Actions can start jobs again |
| 4894c5439360de87def27c5ccb440f3c035a9f5f | aef9fb41b52c5e91a988ca312d152e81ad2902c2 | 2026-09-21 | Merge remote-tracking branch 'origin/main' into ci/phase2-validate-and-manifest-coverage |
| 0b5cd9141d65089d19113b6cfebe897bbe2fe0d0 | c5f43a551a19fc82a2debe79f60c44736bb85a7c | 2026-09-21 | Merge pull request #52 from MrBekoX/guard/conflict-markers |
| 77ceef38d5b3bb23c70537bcc2ca20180a8bed08 | c7875a49c800fdddc64dffb36aa50ce284d73477 | 2026-09-21 | ci: bump actions/setup-python from 5.6.0 to 7.0.0 |
| 99c22a57176e94cd35835b6557800d9673c97a17 | 5f8a92a72abf702c4ca0cb8291b893ea3ef88ed7 | 2026-09-21 | Merge remote-tracking branch 'origin/main' into guard/conflict-markers |
| 47d93004637be0c2748946e18d86b48ca71e6e87 | b361e7d6298f7a6aa1789be863a560a13d554e18 | 2026-09-21 | Merge pull request #51 from MrBekoX/test/harness-negative-controls |
| 40333a1d83be6b7187955a2a372f17ad0c3b15b4 | b326415d26931f172509ae40bcb0402c5c77a3b7 | 2026-09-21 | Merge remote-tracking branch 'origin/main' into test/harness-negative-controls |
| f7b6931b31267f31f1c6132fb78409bfa23b3a23 | a24e06f66d504b4433d8f327b35e6665ec5c75d5 | 2026-09-21 | Merge pull request #50 from MrBekoX/fix/unfalsifiable-assertions |
| ce79fa1c502b392502e6ad37c274fb99181f8cf4 | 8e908943439c968d5be8a12b0429c849244a9697 | 2026-09-21 | Merge remote-tracking branch 'origin/main' into fix/unfalsifiable-assertions |
| 455f5f8f2e535cf7254606873b5e2f8d1b41ad6d | 5baf3f397a3b12704e48f7f0755a05668eb22a3f | 2026-09-21 | Merge pull request #49 from MrBekoX/perf/gate-composition |
| f5b39eec41bbbfc87a563bdd50b4216d15650654 | 7868c996e005bd3be158968fd50839e9f5d68e66 | 2026-09-21 | Merge remote-tracking branch 'origin/main' into perf/gate-composition |
| da6ada033b22a731e0d95a424212cc13c2dd3dd0 | a530e4654b2decf282359ab74abe21df625783fc | 2026-09-21 | Merge pull request #48 from MrBekoX/fix/plan-frontmatter-validation |
| 1797bf8b204786c1898a6c14f0a710fd9eb0eff1 | bbbda1788f58fa0892472d227325fadcf51ae74f | 2026-09-21 | Merge remote-tracking branch 'origin/main' into fix/plan-frontmatter-validation |
| 430d78bf5207e133e8c7fedfb1beb979a4cd296d | ff1325add8f300004ebaa3eef145be0f581675c9 | 2026-09-21 | Merge pull request #46 from MrBekoX/fix/byte-locks-falsifiable |
| 10daaa31567fea256e85b368154db65966b542e2 | 9869b2e207f5d6efb7dd72bf37cd73df19f980d5 | 2026-09-21 | Merge remote-tracking branch 'origin/main' into fix/byte-locks-falsifiable |
| 8fff7c7be84d5b8b69015d66f75902ead68ee368 | 5697029b4c2cba611ef35c4af501a89a9a5e82b7 | 2026-09-21 | Merge pull request #42 from MrBekoX/fix/runtime-adapters-grok-zcode |
| 36a1d77fe23c776b1b89d7729e9c6fbdd0e5bd99 | 5f1163441d326e1eaec67cad11bb2d27bdb46a89 | 2026-09-21 | Merge remote-tracking branch 'origin/main' into fix/runtime-adapters-grok-zcode |
| 9d3969203e043310e4642bd1df1050d55b6d7a68 | 1f3a9eafa60d458f217f85f56b8244fb8fdaf96d | 2026-09-21 | Merge pull request #53 from MrBekoX/fix/git-path-prefix-parity |
| a6d13e34c37900ecb07a16231499502204204928 | 4606321776701f7f0af9b659a08cd7b4d2b5e374 | 2026-09-21 | Merge pull request #45 from MrBekoX/fix/git-dir-aggregation-cost |
| afb8377c1e45faaf5b863e9a409084acd61e64b9 | d70b7d6a1e6a25aab90bc1475ad6d82c129144a9 | 2026-09-21 | Merge pull request #43 from MrBekoX/fix/command-guard-prefix-parity |
| 95a6be053ac296607a2bc8539b0b0722310320a1 | cab795d8e2f10bf0db3cb17ff91516556b694779 | 2026-09-21 | guard(harness): fail on a conflict marker in a tracked file |
| cde04d4d761287673efe132f27c517f9cc7410a6 | f3985d4b0b4e8f93198277f9d06fc205239a7a23 | 2026-09-21 | fix(zcode): make the stale-claim sweep subject-aware, and map the Grok workflow suite |
| 3db63618e627333b1e68553c60193b737b1d797c | e81e78aec0602296430c507d8fdf344401c5055f | 2026-09-21 | test(harness): show that every check the skill harness performs can fire |
| c6a23bb7b0bc5f1fba6a55af7d8aa3e64b6479f8 | db021ff2e5bfdc6f7cd4cdcc7a03cf4820ef9457 | 2026-09-21 | fix(harness): keep the settings.json check inside the hooks-README branch |
| 0390738fe944850e37c5b53a9b5b3d845149522f | 5bcc478d616f9d0946ecaeaa90cc5ac2be175e89 | 2026-09-21 | test(integrity): make ten assertions able to fail |
| ace08fce90454bd6b6c2251728d1dae900944799 | 931e8510b9a047d142391094d20a8c8f181ebb8b | 2026-09-21 | perf(gate): run each suite once, and make each reported key name what it measured |
| 57f8f75a1c5e85bdd390ac068758428d136f857e | 825ddb2aa5e37112a90d40de8893ffb316045eb9 | 2026-09-21 | fix(validator): check the frontmatter the pipeline already gates on |
| 34d73ab75775f98ec1e8c89bc81bd57514b461f7 | e6074c0f02c2456b81ff3db844485e4e72f620fa | 2026-09-21 | docs(testing): make the suite map complete and the promised skip real, and pin both |
| 3eafd72a611ae9acdde17e81f5b25b3a0a90d4a5 | 7fb84dec78a6abbecf7356dfe1641266c4d3e65e | 2026-09-21 | test(locks): pin the regression surface by literal, so the locks can fail |
| 2ce88b44bbcc47cb8d6882e27fa54e86f2c74795 | 32569622e68b1eb6bc815c25aee9f75ea7eb4569 | 2026-09-21 | perf(guard): collect -C directories through a Set, and correct the severity I published |
| 3a62485b56cf2efd4c1e7d775ead324b8862d0f7 | 39f310d80b1c365ba5b830097e55305b3ae8ca95 | 2026-09-21 | fix(guard): give the git resolver the same command-prefix grammar, and reach into -c payloads |
| 0d0f926a626fff411fff228f542724098df0ff86 | d83329d60000b56d188e5ebd64daa5d42755774b | 2026-09-20 | fix(guard): resolve the command name past every shell prefix, and bound the walk |
| aee2da98049608f878a7bae7f932ef8f1893271f | 53963bdc819dc91e1b021bcdec980c891af74ddb | 2026-09-20 | fix(adapters): make the Grok and ZCode guards observable and their claims sourced |
| d1104123139b66d2c2fc0bf8dbf565a6f39226a7 | 5a7c70bb878ed66ce3ec08430619d9bd01889542 | 2026-09-20 | ci(validate): run the official plugin validator and cover every manifest |
| 1752cce3700c0431dae9d2d75935a2265ce3675f | dbea8fa29cd43a4772a62c394fa9c4ba7e9ee10b | 2026-09-20 | ci: bump actions/setup-node from 4.4.0 to 7.0.0 |
| 715e3164e771e8ea29cde76d6e709c7fb885a432 | 824699199519c00e45fe088e594723f30149b783 | 2026-09-20 | ci: bump actions/checkout from 4.4.0 to 7.0.1 |
| 82230cbf0d3f5ecbf92925f1a64387954f0a0d03 | ed9521a7e28c299524db9c9e9317c9de6c74830d | 2026-09-20 | Merge pull request #37 from MrBekoX/ci/phase1-workflow-hygiene |
| 32f02ceb068f260fa3d7c17bf72a20ad1cdb7a90 | 214f11bc823cb7825463611fd9df5f0dbb5299b1 | 2026-09-20 | ci(workflow): gate main on push, bound and pin the run, add a single required check |
| 6791408e6c060948f6e43583db77ece562a2a72c | e6c2909fe01fb3c382ac794c14d1a249633c4f57 | 2026-09-20 | Merge pull request #36 from MrBekoX/docs/readme-new-logo |
| e445a8f6a4ceabea0da17ca0af54f281ccacdafb | 78aaa9a0245e01cdd1fede97e6ca25f9c6e196c5 | 2026-09-19 | docs(readme): use agentic-sdlc-image.png as the project logo |
| 5e9d1241e8d681aa0327c6abcb8ac1bb015924bf | 3a283a270975a716e6db2e11bddfad5bce6219bb | 2026-09-19 | Merge pull request #35 from MrBekoX/feat/grok-adapter-packaging |
| a69622337d7626dcff90abb1a7dfa7beae3c60f0 | e7b8f9ba8db82409cf90f1fff93e197ee6ad9ab7 | 2026-09-19 | feat(grok): add experimental Grok CLI adapter packaging |
| 281e1351a99d8469874abe0f4fa796fd42503f30 | 120e6073d59cc2b53c98bd5a72d4c367a7df22f7 | 2026-09-19 | Merge pull request #34 from MrBekoX/feat/zcode-adapter-packaging |
| 116f230af7fed61294fd7f5934d8b150c7313e9d | 80fcd0e0492ae8143927c4c044f8a642d658eb03 | 2026-09-19 | feat(zcode): add experimental ZCode adapter packaging |
| aeb356ffc42765aa0190a7b10c9892ef3e22208e | d1a76428d26184327f8132c9a4455dedf21d1775 | 2026-09-19 | Merge pull request #33 from MrBekoX/test/destructive-guard-flag-variants |
| abe2a515bc5a957b59b1e26ea4a1c03e92de4475 | 782739c8268ae80c4792bd694b8ab97f35555f4f | 2026-09-19 | test(hooks): pin flag-order, flag-first and case variants of recursive deletes |
| be5cef09269fbd6599dd929f7ce20e7eea4e33a0 | 2e93039f2f2e39c27db32a508cff9ef2405f0acb | 2026-09-19 | Merge pull request #32 from MrBekoX/chore/ignore-local-prompts |
| 8479d83d59bb829cae6611def41894c386cb1700 | 7e16b0c15cff8ee93bc90938e419dfa0a5b4719f | 2026-09-19 | chore(gitignore): keep local prompt inputs and their contract test out of git |
| a342d1b7745b2197b04abe0a55226e9a9bb36f1b | 2781fc533657764909de34b350efe3e203a4a2ee | 2026-09-18 | Merge pull request #31 from MrBekoX/feature/publication-readiness |
| ed9818cbdaf2f1af776014101432705bfaddd5c2 | 861c4f1aa596a61f539530f9d94a8e28624b0aea | 2026-09-18 | docs(release): drop the superseded pending marker from the local_gate row |
| 713855927aae6deb7b167fb37776459cdbb8d180 | 3316e92980ca1f534bc96f3a0d2a8154f76c1e0e | 2026-09-18 | docs(release): record final 0.4.3 clean-clone gate counts |
| 54ab1566e3d4f55e7e0e5dc4167871990d7afecd | 8089c1ebca135d1477c8ec999c5f75743f4f7409 | 2026-09-18 | docs(release): record 0.4.3 live evidence rows and decision values |
| 2a3d6ac31edce141795f8a38dadc75f672adfaa1 | ab4a72f7beea0c7106f7787299a2bf33c92225ea | 2026-09-18 | fix(portability): accept `~` in a Windows path and stop a test asserting the environment |
| 7b17f9f5e7b21f6bbb30462d535b1136212a6c70 | 4e561b5b502d9f801188b09d3f5991c7c567a4fa | 2026-09-18 | docs(release): bind the ledger to the release commit and say what carried over |
| ac944da3a522c928463c38a810b3bfb4f1b7fbf8 | 9b1f6b4a48396bc5093b062dae9c7f93ff36ee65 | 2026-09-18 | docs(release): fill the 0.4.3 evidence ledger from the live records |
| 1d06ffc84d66e971957667011221370b736b60ec | 12427d0b27a2448a0ca3bd24c012b8d18a759106 | 2026-09-18 | fix(security): close the seven should-fix findings of review #2 |
| 4b4160644db4adffaa17ea05d6078f86cfd9e8bc | bf5a56b89f93fcbeda82a97f1a34e676bb7a484a | 2026-09-18 | fix(evidence): redact split secrets and scope the gate marker to the current turn |
| dc2e2377ca5484c82598a78cfa51620d865e233a | 5f994042e6d13a701b846af09edfa8631adcd497 | 2026-09-18 | fix(scripts): stop calling the deprecated datetime.utcnow() |
| 7bb024445975868387c14e3c407cc81a622320fb | 0cef1c86031c7947fb1c1ff9176b931de682b743 | 2026-09-18 | fix(procedure-eval): keep the payload identity when a foreign scripts package shadows the import |
| 26b0fe1983b379bb2dc70d2192d52f9572b0f52a | 408fa8c47a4a213b5d5f0e6538ff2132fc19d7fb | 2026-09-18 | Merge branch 'slice/r10-publication-readiness' into feature/publication-readiness |
| 3e9f9971ba4c697cc7436c7b036df21976dee0b6 | dc645e1c092fa67767dbec1ae149a6e9f102a6f7 | 2026-09-18 | test(br6): pin the long-option anchor in both mirrors |
| 9fab83b6d8595dd44a648f24fba107189b5a74d8 | fa429f252fbf9a1cd2223c009b08a67c3f8fa930 | 2026-09-18 | docs(br6): record the long-option pattern flag ban above the constant |
| 12f494bda356bed32a532519c186f4e3595c830a | 00664f00e6016cc014fb5d98dc349b32ff8218d0 | 2026-09-17 | fix(br6): read every dash-word shape in the version and help check |
| 429eba323fc6c6eb2d008cf9aff2ec373178ab75 | f9d90583c18f7b8440d14edae3724d98c9f6d736 | 2026-09-17 | Merge branch 'slice/r9-publication-readiness' into feature/publication-readiness |
| 1a858846ccf2ce7d5b094a83c8a7973f15f38500 | 95d2fd2bd5679de25300924765be8b8afd809f17 | 2026-09-17 | test(br6): pin the D29 one-statement, orRun and carrier column summary |
| 5d8875c6553b921d49b27b6d049419ce5dd308ad | e05939fe5a2f33a61d90ea3d76c619105157f19e | 2026-09-17 | fix(br6): read redirection-target separators and key letters anywhere in the version and help check |
| 0964febdd7070038ee34e283320ec9ea70b81625 | a8c92ead6ba50709d4a40924d8fc0307d6d3ca7e | 2026-09-17 | Merge branch 'slice/r8-publication-readiness' into feature/publication-readiness |
| 812994a80cab2acdafc0ebf932a8e66016fe8735 | 47f2cc258d40c634a570fc6bd9a73340c636ce83 | 2026-09-17 | fix(br6): make the version/help cluster checks linear |
| db4abf83f96ef9552a02704df4c577d8d1d3d5d4 | 94d6ecc4988669b6c4798229454068ed957d3009 | 2026-09-17 | fix(br6): close the pipe-newline, launcher-selector, version-option and script-name gaps |
| 27a4619672097c9f26bde3ae9a701be07d1dbdbd | 4dcb152d333c054db04084568f608d5a51ba1482 | 2026-09-17 | Merge branch 'slice/r7-publication-readiness' into feature/publication-readiness |
| 3cbea86aabdd29fe80501d71d6a6de8a5f1f35ce | 1a0327a914c35df9bbf4beef98ff518f361d270c | 2026-09-17 | test(br6): pin the D27 one-statement and orRun column summary |
| a664eb80a62562d9fd7b0f86b0703eb3c82d7d46 | 6dc6b0494497099e8ca3a7c001551eb38c05f9ed | 2026-09-17 | fix(br6): derive runner identification from the safe-grammar parse |
| 63a70fda60033bd8370f37fb2e3826361ee1bad6 | 07da8f1d5904e11335c36dd7c5cae6018f7006e7 | 2026-09-17 | Merge branch 'slice/r6-publication-readiness' into feature/publication-readiness |
| 97eb7921b3f7d2b167fc6d0042d6ac41b3a51de9 | 5f90f73be54d419bd472ff165e773866a22eb2c2 | 2026-09-17 | fix(evidence): keep JSON escapes intact when masking home identities in tool-input source |
| 9f6cfa61922784b868da571133818f126d768c34 | 5ec74ada6e63805a7aec8f10f7137b6b917df7f2 | 2026-09-17 | fix(evidence): mask every collected home identity in evidence copies and packets |
| c00e0f2f9d8d3ba86f1e99961d870f359c6ed0ec | 1710e560b55b76e37e084bcd33f93846f19b7615 | 2026-09-17 | Merge branch 'slice/r5-publication-readiness' into feature/publication-readiness |
| 0ba25eaefa390d0236be16080d6d80e2180b443e | 2e47b67bea2bc834f4964e00d58575e2c16e2291 | 2026-09-17 | Merge branch 'slice/r4-publication-readiness' into feature/publication-readiness |
| 623446ec3d3bff3735da1f64891d537a03e7904c | f2f970948e350bfa979999d48201d2df02b2be95 | 2026-09-17 | Merge branch 'slice/r3-publication-readiness' into feature/publication-readiness |
| b5efba990ffaca3bd10227be14e432b052fd16b3 | f0b51ad1c9ee0f8b5f58714b0f7c3de291f3d8d5 | 2026-09-17 | Merge branch 'slice/r2-publication-readiness' into feature/publication-readiness |
| 60fe633e3b1f194de70b7b4bdc59bff2796e154f | 4402ec40bcc8e04d1ba81154054250ed5e61f482 | 2026-09-17 | Merge branch 'slice/r1-publication-readiness' into feature/publication-readiness |
| 9a8ed1a5deab9836f9133d31331905432c1a4697 | 9f63683402b24e3a6a91c4e5b4a1e1fa299f58d2 | 2026-09-17 | fix(eval): mask spaced and case-folded home segments, keep scalar lines in key blocks |
| 2ed967e13518ea5169f25c41bb8c88ef6e5756e3 | 2bc2a48fc9081983a0e59e21b3119aef7acebeb1 | 2026-09-17 | test(codex): pin the literal and canonical check in deliveryReadSkill |
| 4dc457437631af2092c2540e478e9d4e7874fcb2 | cc6c1df7327014c5d96815b72317c10c3c43c8bc | 2026-09-17 | fix(release): match credential file names after Windows name stripping |
| 541127e6f7f73c96df0d2acec3a9851fb75017c0 | db52f95e251fc1939b85436a5a93ac3624e96f02 | 2026-09-17 | fix(br6): apply the D25 word, segment, blank, delivery-path, JSONL, lookup and redaction models |
| 71d30a81f0e90d1bc6c7b647edf015c796d7d9f7 | 04d3c992e8e4394d8bf28d68123de1f502741d28 | 2026-09-17 | docs(release): bind the verdict template, document D25 limits and pin ledger rows by blob |
| fe0a2fe017f5a443c573ced1cd36b5623d594fa8 | fd513c355eea749c8c78355ce10130a17ef6d9e0 | 2026-09-17 | fix(release): harden archive member policy, credential names and tool errors |
| d33412c2bf0fea28bbb3c4842e8117d316ffb558 | 9a88d0ea495d8df7416e4cfd54fd25ba2e6006fc | 2026-09-17 | fix(guards): resolve git by absolute PATH and close three durable redaction gaps |
| c995097cf09f4079c5b5cb1dd25a11845a415ca8 | 20cc50fb7a730035b571593ab05da38ac9039c22 | 2026-09-17 | fix(version): bump every visible declaration and pin manifest drift |
| 82a22abd7bf87365380fc77bccbe4717ad4422a0 | d7a1d0361cdd4c722737cce6f1bc59e2acb90c1e | 2026-09-16 | Merge branch 'slice/f-publication-readiness' into feature/publication-readiness |
| cc7ead17af1150930aac639c6b6c0c3d8dfb709b | 97654802a9b736aa350dd45175e6eb8c496f3959 | 2026-09-16 | fix(docs): record the identity re-check and state packet and trust gaps |
| 1ee37d55b78076407e19a8e4179b266c5d9b8fdc | 0dd466cc3bb194ebb117199e65b5fad7fefa6eed | 2026-09-15 | docs: publication readiness docs, ledger structure and packets |
| 882180859c6306cdc1bef1382a965a466554b1ae | 50accf386986bc5d13f18ad5cf361f54d8e21bad | 2026-09-15 | fix(codex): resolve the trust check's executables on PATH only |
| dd289e2a64dd9c0151777e6e3514353d085a159d | 4ad0bea5a9fb45533fb0af050343cb49b1315a47 | 2026-09-15 | feat(codex): add a read-only post-install hook trust check |
| 366c3723cf04afcbc16145385fc9a2b775708523 | 16b5df049882fb10ae7605868236300f5c066e56 | 2026-09-15 | Merge branch 'slice/h-publication-readiness' into feature/publication-readiness |
| 4320be79e9a2f5b5c429ba78e75d486ecdf73b3b | 385adc2cae30815633cd840b3d6d58d4141e68c2 | 2026-09-15 | fix(br6-grammar): keep integer-attributed assignments outside the safe grammar |
| d781116329ef081e1dea8a97a22c535ca35831d8 | bd9b69a2dc2dff688651e4b89bcb5ba3f0129c5c | 2026-09-15 | fix(br6-grammar): minimize the safe builtin set to close expansion forges |
| c1b64cd86118285549c57a754b98c7a6b47cd20d | 907a93e1d1ca01fa2ff7558cfe55035920bd0bd9 | 2026-09-15 | fix(br6-grammar): close parameter and glob BASH_CMDS forges, fd in any position |
| de7331a2897dc72a778a1425361fab0b41f2ad8d | b947cfbda31cf2a1aadd21b193cf6ab94b382455 | 2026-09-15 | fix(strict-eval): harden strict grading, BR6 safe grammar and per-line secret scanning |
| 072497aba22d18b70895ed4cf7bd33f237e877b0 | 7ac3687349ceb219aafafd0939a53b1f8023f716 | 2026-09-15 | test(procedure-eval): make build_release stub patch the identity loader |
| ca6b496621f1c329a5e0900ed5d4a9f7d809868f | 5daa07fe90ba278d458e94f86d90c7d08b7f67ae | 2026-09-15 | Merge branch 'slice/d-publication-readiness' into feature/publication-readiness |
| cdb89ba32280d051fc86ba8dd292fd1c9827dd4a | 2d30de0dc9fad748e93312530e7bee4c44bf1c9d | 2026-09-15 | Merge branch 'slice/b-publication-readiness' into feature/publication-readiness |
| c1737eed32903f7607a31aa5954ac316972c13c1 | 91186ecf185278bbb0e81df395ca033c09a0f23e | 2026-09-15 | Merge branch 'slice/c-publication-readiness' into feature/publication-readiness |
| 5ede72c55d4f17a36e1106ea4d7d6c1a61206904 | 209f01735b1b0212a61d90ca9a1972d741c9babe | 2026-09-15 | Merge branch 'slice/e-publication-readiness' into feature/publication-readiness |
| 510b3a744851e8148a48f8e8a8e701403daff403 | 8a90683158ef50a33d0afde998de70e48cd90f92 | 2026-09-15 | Merge branch 'slice/a-publication-readiness' into feature/publication-readiness |
| ecffc56f5b66274cc090962f4514e50180b52e5b | d95762e6fe87c3ec76986f5c70e94d913163adf7 | 2026-09-15 | fix(hooks): fail closed on unmodeled shell syntax and leading-success \|\| |
| c8f619eedf95914bb2393ed91146ccd24c0fc143 | 47aeb58fd14dee2427b6076779744b0b675ac5ca | 2026-09-15 | fix(hooks): start BR6 comments after every bash metacharacter |
| 2b3d3b02b60624664700b45dde41980f551180e9 | 568a9c0077a3d931a7c3da11a097870568f973e9 | 2026-09-15 | fix(release): scan non-commit refs, name unreadable members, mask scp user-info |
| 64b2fefac1985c286df9d7a2ff00b8560b07d5a7 | f0e261ac2e8fdd24aa1820fcaba70a3be7dd65ba | 2026-09-15 | test(flow): pin warn-only reminder ids under the gate block flag |
| 80ea1b8f6ba027291c73382794ef436b3b0e5f6b | b7a1c6079c53d8bf114b77bdf3834f3f1ec5bf70 | 2026-09-15 | fix(scripts): split strict evidence preflight records on newline only |
| c67e0801b9686109e495206330d15b34c12b5cf6 | f7a52cbd89a2ed500c5351213ea2b3539f778eee | 2026-09-15 | fix(hooks): close BR6 mid-line comment and heredoc exit forgery |
| 5b68b1695bcee8403dbc54aff95d5ca5f1c75a00 | e93ab43c74da9029c80bdf8088a2d8583d933e2f | 2026-09-15 | docs(data-handling): disclose hook alias, message-file and worktree-scan reads |
| 9d86bada0bc05fa2207f8765a563468a56b41d55 | c2c7c3cf7e493dac6b2d13fc0135ba07603a54bc | 2026-09-15 | fix(submission): report symlink-loop fixtures instead of raising on Python 3.12 |
| 4c4f894c610fb42e74dd593eb05d392ea5bc5e11 | 0595b8f77f8ec1d215146f69b8bd93d1930db86f | 2026-09-15 | test(submission): add eight native-evidence submission cases and schema checks |
| b9af9dc609510a4bc0b38b1d6ccbad57ab66a75b | d40434844644f3e1fc653dbfb0828cdb4ecae702 | 2026-09-15 | feat(packaging): listing rules, version declarations, link record and data-handling disclosure |
| 4f32e86b987b0262a7134c3408131f5e3e96fd97 | 93938716e68c93e79bb9940048056f6a32253c24 | 2026-09-15 | feat(hooks): exit attribution closure, warn steps, strict evidence, owner-aware codex completion |
| b38c7dfd793263e886db8c66138dcba05f295ac2 | 3a183b343eae0ab1e77365dc7bf76c048c4646d7 | 2026-09-15 | feat(release): build, verify and history-scan distribution tooling |
| e2f6973f7d4479feb919332e93fcbf2c183bf8a6 | 0973a31f89167d4bf0b4a95bc8ab366179191818 | 2026-09-15 | fix(procedure-eval): full tool_use block authoritative; name evidence write failures |
| 66df832cc4f79426589f3bf438944a4da6c10bbe | e10ce1f9c4ea98c3725cb0771e2e028dc122880a | 2026-09-15 | feat(procedure-eval): strict evidence grading, fixture-root containment and evidence packets |
| cf68b367fda054b984abbcab77be4a76e7fa0720 | 5d9447fe55398c275c55f19b4de2a5c4539b3696 | 2026-09-15 | test(flow): add shared BR6 attribution case table |
| 5801cb9894c349b656ed3714f7c9f629956ac8c2 | 32eef83e2f79de1cc1bb56302e9682e238140e4c | 2026-09-13 | Merge pull request #30 from MrBekoX/fix/dual-runtime-production-readiness |
| 9e8fac7f910110f38823e7188a3cf5d4b8306fc0 | 8961ef6242ee0713ed0e7e970ed727463ee0c3b6 | 2026-09-13 | test: normalize resolver expectations for Windows paths |
| 4d88cd7d690e25bb3c7b01a3715fd82580b51533 | 55a6f06b7a46d1eb498c4947bd51e004ec405d03 | 2026-09-13 | fix: repair dual-runtime skill loading and record release evidence |
| 60feffdf46d7222f9c74dc2e5f9b92d4d9a84ef0 | 63136da9c3988e57dcd25457c9e336ceb1e86fb8 | 2026-09-08 | Merge pull request #29 from MrBekoX/cursor/codex-listing-compat-3f42 |
| 6905f10962ed4953ea1882af1d210cdce3e0e6a9 | e13596c968a8b4a3045ee80005ad94df297a8938 | 2026-09-08 | chore: bump 0.4.2 so CI release-check can pass |
| 7b0d5f4d30adc65582677c7d4817b56ad05d5f5d | 2c653aa52f13b32cf1a30949c926525b201729d1 | 2026-09-08 | fix: close Codex listing and install-doc compatibility gaps |
| 25932e62f57f8c41b4031e1ca3b8983ff401fdd3 | 610c2a2f2262229da34bca147d69f5c3d788931f | 2026-09-07 | Merge pull request #28 from MrBekoX/fix/flow-gate-critic-evidence |
| c2327c5c7c427f1684c5287702ecb2afaa17153e | c5d03cabf0cc0cd61daf84a3a39337e54fa1edef | 2026-09-07 | fix(ci): make the public gate independent of local checkout quirks |
| 1e1c10d130f55cb493902a759f02371b90be0d70 | d9f0f59b340dcee794bf856b562411738f71b374 | 2026-09-07 | fix(ci): skip local-only dogfooding artifact test on a clean clone |
| c173b99a86d58246020de8ea3d1f9bba9024c411 | 4effaf8414af21af151052d660443bfa3224241f | 2026-09-02 | fix: close public release audit findings |
| d805d2963a2111d81947971d0f9b52d6948fe46c | db7d381f22011b98f973a1f4ba14a5b9edfb2cca | 2026-08-23 | Merge pull request #27 from MrBekoX/feature/per-package-evidence-layout |
| e03a2ec97285dfbf1a21870539b6e914078af37a | 2481ec6935140ec2db75fe91cad9647f8c0dc4b1 | 2026-08-23 | fix(hooks): keep hook sources text, not binary blobs |
| 8c83322debeca236d4c9dc89a163869ee5d1d50f | d0c22a6d0dab5b57e4b8bf5e0605ab3554dd3f39 | 2026-08-23 | Merge pull request #26 from MrBekoX/feat/effect-layer-enforcement |
| 7d965279980ddaf47a104daed3655a22579bab65 | 2eb6197380c55823ee431afd5236a93a3c1caf3b | 2026-08-23 | Merge pull request #24 from MrBekoX/fix/command-guard-bypasses |
| c043c31a7ed97994dbccd2b2778cfe80e25ba93c | 4f048f0cdfa8bd5325790fd73d3bb24988745912 | 2026-08-23 | feat(hooks): add effect-layer enforcement below the command guards |
| d4accd18d305c4372786f38c4fc3558f9c448d96 | a185ecaa3eb42fb5c016f42ce06d8ff2058a597a | 2026-08-23 | fix(hooks): close the command-guard bypasses found by the multi-lens review |
| 2c864d3cd66a84fca66d57317d8f92bb093a398e | fb0da6bb66dcec8614b275ed6e37fe5b4f48ead7 | 2026-07-01 | fix(hooks): linearize parseBash subshell strip -- close default-on ReDoS (#6-C) |
| b163ea6133479718ffe059ce18582dbae0dbbb60 | 2f7a62ed5969220bd102a620b85b73ff0cb3558e | 2026-07-01 | feat(hooks): close Codex flow-order sed/tee/redirect write-form bypass (#5) |
| 4c49fca7ff37cdd6e8463b741f1b855ab4e97a39 | 214667b1ef6a428b446b123c2ba8fc33f1785141 | 2026-07-01 | feat(hooks): harden Codex completion-claim marker + "tests ran" evidence (A1+A2) |
| f77c87599622b9c13abd55e09884c6886b6b7e40 | c1b450257f02b07a6e1df1836af702f67fd38952 | 2026-06-30 | feat(artifacts): per-work-package layout + evidence persistence (dual-layout) |
| d069d3c91a20a190f7e6e6a95d58c3f54cf2184e | 2e0902040730c3e9895d9ffe62a14c2aef2e02e1 | 2026-06-26 | fix(security): close two ReDoS DoS-bypasses + a path-reflection leak in the Codex hooks (#23) |
| 6a1fa879321523863fabe48eb0fadc41044b17af | e76719e480b401fb560caef76fd0a44bf0fbb2c2 | 2026-06-26 | fix(hooks): detect sed -i and tee writes in the Codex rollout reader (close B3) (#22) |
| c4973fcce2895a66d5bad929ff2eef3b36d2d6ff | c1c350fc848bf438d14f29c802f26a891a5ce59e | 2026-06-26 | fix(hooks): flow-order accepts a before-edit test run as ordering evidence (close B/DP-SCOPE-FLOW) (#21) |
| ac00d50451a85f311c4985a92e2d749e6fd7157a | ce98a64d1e077328046054d43c74f8ca8002dc31 | 2026-06-26 | fix(hooks): broaden the testCommand allowlist (close B/DP-M) (#20) |
| e6b8f18e9e4f9c8c1909b1022df6f15690eaf015 | 1dc5be03c6a5cc747ba2a3b61fadd5e79d847083 | 2026-06-26 | chore(release): bump to 0.4.0 — Codex v0.142.0 native deterministic hooks (#19) |
| 8e8562ec768e0e916ca6f72f340ee2e5b013e141 | c76f7eb9347ea1c6a44b23d83dca531b04fa8afb | 2026-06-26 | fix(hooks): decouple the Codex flow-order env from flow-step (A2/DP-ENV) (#18) |
| eb492749432204410e2b662e65bb58337ba32a31 | 49d06d211b76855cc8be96ef316dd67d258152e5 | 2026-06-26 | fix(hooks): detect shell-redirect writes in the Codex rollout reader (close A1/BR4a) (#17) |
| 4c8259f02bf2adb43b988b2a54aa5c7791b1ae46 | 514593071983adcca0ee6ee3d1fbae347c2c8ecd | 2026-06-26 | fix(hooks): read the real apply_patch carrier (patch_apply_end) in the Codex rollout reader (#16) |
| 86376ca09f95f5b1244b915636aa5ef0ff18e8e7 | ff640beb4b04315d40017a6e12decaffe458dbd3 | 2026-06-26 | feat(hooks): wire the Codex flow-order PreToolUse pre-edit gate (AP2c) — AP2 envelope complete (#15) |
| d317a77d56c8a5775c909d8add26e105aba09a55 | fd21f21641977e00b187c5057a2cad15a4f2a05e | 2026-06-26 | feat(hooks): wire the Codex flow-step Stop guard via an evidence-only rollout adapter (#14) |
| 7ae12fdf0229f1a8c4c01a4dfedf774c7f8d253f | a26b0f149e9192c331c86d66db5f3f2a6eddb232 | 2026-06-25 | feat(hooks): wire the Codex completion-claim Stop guard via a deterministic gate marker (#13) |
| cd7fd1013b6e0ed006ccba20a2fc10126ba9734c | 252ed5a0d8d6e637f747701f34f0e3785e8bf82a | 2026-06-25 | feat(hooks): Codex v0.142.0 native deterministic hooks (command + write guards) + AP2a defer (#12) |
| 9c28571cc2d161f7d242509577a19507bcf34f6c | 5f9835e2e14790cfec6b31d949df89aa44242b61 | 2026-06-24 | fix: adapt pipeline procedure eval for Codex |
| f1a40bcb46ba314ef796df003f5fe80379ec28f1 | 8b5499f41f33fa59891422d0240080c0f554dc67 | 2026-06-24 | Merge pull request #11 from MrBekoX/fix/scripts-utf8-subprocess |
| fe4e5dd798463554091f656ea0ab834ac3082154 | bf7ddb69c6835d2ecb525f5aeacd0d7a2ab36a82 | 2026-06-24 | fix(scripts): decode subprocess output as utf-8 (locale-independent) |
| b20c58c41fec26a53399618e9ff72a162f3e3266 | b62491472da11497ab209971cbff7ca5d2bbcc7b | 2026-06-24 | Merge pull request #10 from MrBekoX/fix/security-hardening-and-gate-utf8 |
| 297789535e8c2b116f35dcaedd6ddb8115b8d44b | 711ffbb247ee1682f84b711e2b0498a85da41548 | 2026-06-24 | test: cover security hardening and make the gate locale-independent (utf-8) |
| abb031f36378c05a758e3fa36941a9e55a3498e6 | d59d174432590ad2ff79b3867e52169c0367dcda | 2026-06-24 | fix(security): harden destructive-command guard, secret scanner, and injection surfaces |
| 60546ae05c1cf378461bbddd13c766089a20f504 | 14a1cae0e29b6e588b0889759e03cc2a8c70719a | 2026-06-24 | docs: update Codex personal plugin path |
| ba53c92496db40ebb7b9934b21232ba631f4c15f | 78de3830ced15d91542cb69cb5500bb0dfb2f074 | 2026-06-23 | Merge pull request #9 from MrBekoX/feat/dispatch-strategy-scope-fence |
| b57d5c3765a94db0083bb717a6fdbcf1ddcd0376 | 97a04d986a07c05de199f8c2798d8786d59cb7dd | 2026-06-23 | feat(dispatch-strategy): fence scope to mechanism, never a skill's internal flow |
| 1cfb7ad2570f31d3346dd68d9237e045bc3cb750 | 772db3680cfe0bdda225a879b1805d4a031b78f4 | 2026-06-22 | Merge pull request #8 from MrBekoX/feat/dispatch-call-order-guard |
| 60426ee0a9e21cbdc414186cb9b156700976aa5c | f9f3e665a8d584a231644d56377c28cfec2a4006 | 2026-06-22 | chore: gitignore local debug/session transcript artifacts |
| 3b0ce79b6e8be02f7885e31849a7469fbbcd352b | d39b9efe5fb1b71d94b6a6a78a9e2f681afe8c3f | 2026-06-22 | fix(hooks): skip flow-step-guard obligations on diagnose-only runs |
| e5cb644273ef371e43d3e5a8f8752cae3956dc11 | deb1830075a14c2e0b9c48247817893bae64a9b4 | 2026-06-22 | feat(skills): add dispatch-strategy call-order guard to the six work-skills |
| 751d5a8633de320d881cd5436ac0ce00283ebef7 | 387fa19d1344e963374abccce1314beefe8728ba | 2026-06-22 | docs: refresh plugin layer documentation |
| dfc5ca8354fec7d05454456cc9bd6c8caa82e91e | bfa8c7458432f85fec5d54322515bd356cfd3c62 | 2026-06-21 | Merge pull request #7 from MrBekoX/test/generalize-hook-config-guard |
| d8b05082918c59e32b4d4a366ab497982a36c842 | 30bb37ed4f022ec9b9abe614e6f3d9838a6d74bf | 2026-06-21 | test(hooks): generalize the Claude hook-config guard |
| 3f6fbe0234ecd0bad6c9742144e3a0a13ddc7fe7 | 86b9e8f1321156ca45f87aa2862a9956ea6bb566 | 2026-06-21 | Merge pull request #6 from MrBekoX/fix/codex-hooks-config-collision |
| f57fa1b730228ae75df4e577ef711c5a25f22b94 | 6aeadad2d4344e0176cded919f59193e93d17963 | 2026-06-21 | fix(hooks): stop Claude Code from loading the Codex hook config |
| d9c22d2907a45bfddd5589559faf95c9c5096db6 | f36f5a05fc580077b1274a957c509deef7cf0de3 | 2026-06-21 | Merge pull request #5 from MrBekoX/feat/author-depth-contract |
| 0f1967af886bd9368261ba14252634620eb77b19 | 0ecf5f48040061ffa2e54b10efb2ea3970a3fe45 | 2026-06-21 | chore: track the lessons.md log + ignore the codex runtime debug report |
| 0b40943bb8cc6d8c5e81dd3b1b7549b9d760e28d | 2bfae093ac5d270d14b453814d1651b7f9e27c1c | 2026-06-21 | feat(agents): carry the spec/plan depth contract in the author worker |
| 8b53ecbf75bd428e2b40a181bdcecf41335939ce | b1a5343467313ae6fe8a4ed0ff295e526d2a8854 | 2026-06-21 | Merge pull request #4 from MrBekoX/feat/flow-enforcement-and-orchestration |
| d998c8cf8c53c6602720689c461ef21f4e963a6b | 2127a849b6b2277a3f89b06fbb6cb6f9356fe620 | 2026-06-21 | feat(hooks): runtime flow-step enforcement for the multi-step flows |
| 5c08ec2f295866feea61ffca7c5e555adc250de6 | 079fa6287e6444c63efbbd30eae2fe4547375ec5 | 2026-06-21 | feat(hooks): harden destructive-command-guard against 3 bypass classes |
| c2bbe13260bc28713a8f29a186f9fc9bd36deea0 | b2a3242635673f02510131b92493d7da1862b5e6 | 2026-06-21 | feat(skills): parallel specialist fan-out + adversarial-verify workflow |
| 06e4ff24bed9233f92327cc02c6c8f696cfcbc8a | 3db7b2dfacc17ba4365cd5385e260f4cf589fa93 | 2026-06-20 | feat(depth): roll out L1 depth-forcing to remaining 14 skills |
| 4eeaf9b8dcffe0f8cf836c0dd3e8100998995a17 | 1da7154b124ef7cd605bfa9e76be71a84a3e0499 | 2026-06-20 | docs: add banner image to README |
| 59d331827eadb40209bc8e34a38a224fa15a5a14 | 6cbd92baae9705e81346aa0fabc9eacd96da7d98 | 2026-06-20 | Merge pull request #3 from MrBekoX/feat/skill-depth-contract |
| 0a2cdfd71803a5c7f4920d41c3f0bcaba377ebb7 | b58bb1a1446738cfa18cdab321e9358fb6ce30c7 | 2026-06-20 | feat(hooks): broaden destructive-command guard + Codex live-low evidence docs |
| 48c8a8c020990e245ac0aac12f9d146a4fdaa363 | 71d6931aa79a7e893812233bb15a1d10a546d6a1 | 2026-06-20 | feat(depth): skill-depth contract PoC — content-aware eval, biting critic, depth-forcing spec/plan |
| afabb27dc54aeebfc4fe5d7ec72bb2ab37072405 | f2c0f0ca3e6320d8f185c36b1a75b997db80e961 | 2026-06-20 | chore: stop tracking docs/specs (ignored + purged from history) |
| 63234a7b1f7691ccf4370aa48ab10055e9c83db0 | 2738b0e04aeebaceb2ae3aa819bfd025416f073f | 2026-06-20 | chore: stop tracking docs/agentic-sdlc and docs/plans (ignored + purged from history) |
| bdfca54d0c4c40d549fa94f9c4d4dfa9c956c7b5 | e7f4eae301750288e37afdaa0127429e0ccd236a | 2026-06-20 | Merge pull request #2 from MrBekoX/feat/work-package-resolution |
| 56a88dc3433b64de455ac20f3b9ee13a20020da7 | 5d5ed2f6a1964089f9c72a5df06283c7eebdc7d3 | 2026-06-20 | Merge pull request #1 from MrBekoX/feat/v0_3_0-originality |
| a7b61860d618bc22797131b5b8235e1035d0cc1f | 548d023b3560f21c80d9873ab32c37feda0de19c | 2026-06-20 | feat: deterministic work-package artifact resolution for implementasyon-control |
| c937491805b7d40d538a8a5a1e256e3330a31118 | 7b0387f665ad2a94f46771f4ff17e54aa676eb98 | 2026-06-19 | feat: v0.3.0 — original skill voice, Claude+Codex scope, public-readiness |
| 90a1c9f3d0c10e0f4df78273a364e98a5d0a43f8 | 3380e26345fb1af95a8f6beee8b37120eacc27d7 | 2026-06-19 | fix(skill-authoring): resolve skill-creator root portably |
| f4cf92f58e49b2468462cec4eba117e6cc3011db | aa3dd40e87ee1d461e6e54e04445286a7e86fba9 | 2026-06-19 | fix: remove local agent instruction dependencies |
| dd86e971d6840dd4d0582aa2cb0ab792873d2a5f | 0386946d4b2b5cbbc2730766808fe3e0884cb6d3 | 2026-06-19 | chore(codex): remove redundant hooks-codex.json (Codex auto-detects hooks.json) |
| c5f900a207b5aba0c22f1de3c415c42c807b040f | 2d4707386c03083bed9bc6edab23b74cf0b6f945 | 2026-06-19 | docs+test: remove dead AGENTS.md links + genericize transcript fixture paths |
| 610bb32f16c86464535f3da24cda031414cdebbf | da79c804cf826ae185b6838841d5d09c824c62a3 | 2026-06-19 | fix: split Claude and Codex hook configs |
| 1e907d077e674254d620dc4f1401470ba34e371d | 1d6f8b4477ae31413579526ab870a2b91a7bbb73 | 2026-06-19 | Fix Codex plugin publish metadata |
| 74a6b19c75c6d08f7304c321636bd125ff61611a | 81a963c74d19aae96796397601b00c89e1c6df2b | 2026-06-19 | chore(publish): align skill frontmatter to standard + add install docs + author url |
| b9d2a5857b33dbd8e32da95a89fefbd0a3248a58 | 585cf258dca4ea707ef63e93ab9a9318d6b7369c | 2026-06-19 | fix(codex-eval): align trigger classifier prompt with routing classifier + record Codex evidence |
| bd4c959f64bc3eae1378aa3b4320f6843e6531a9 | 6c3de33be6ca5bb60e8adcad511f50e24a834d79 | 2026-06-18 | docs(testing): document 2026-06-18 live eval findings + raise procedure budget default |
| d687102379425235b08aa289abbb51a34de348f3 | 6ec1b83fea11e4940fd1cc72db40095c4fdd80aa | 2026-06-18 | docs: split claude and codex plugin docs |
| 560f6c557e00edfeab8d0be876ab939a657d010c | 4b75d112c849065ffd12c433a6a96aaa8bf785f6 | 2026-06-18 | fix(skills): harden audit/refactor/gate activation + routing-eval reliability |
| df8240593fed948f08f441aa5b06a7961ffa75ed | df8240593fed948f08f441aa5b06a7961ffa75ed | 2026-06-18 | Make skill routing language independent |
| 95ec0721d34b6eed6ecd6eef58e88da789b6dabe | 95ec0721d34b6eed6ecd6eef58e88da789b6dabe | 2026-06-18 | feat: add glm trigger eval runner |
| 48ce119075482591cae601de289f87f4cfe9d5ef | 48ce119075482591cae601de289f87f4cfe9d5ef | 2026-06-18 | fix: tighten agentic sdlc skill routing |
| 82a5e8c91edd58da6afff85fa35b3c8201b6b72a | 82a5e8c91edd58da6afff85fa35b3c8201b6b72a | 2026-06-18 | test: add codex routing eval coverage |
| 9c191041cc67998da638266ef28fdcd26d43433b | 9c191041cc67998da638266ef28fdcd26d43433b | 2026-06-18 | fix(routing): make code-quality-review / security-audit win over built-in code-review / security-review |
| 0ecc613a71f989b87b245b2cbe6600e11b1690ed | 0ecc613a71f989b87b245b2cbe6600e11b1690ed | 2026-06-18 | fix(skills): shorten descriptions to fit Claude Code skill-listing budget + add routing eval |
| 2d60b4254b71b03fe16a1f982f2bad066a593193 | 2d60b4254b71b03fe16a1f982f2bad066a593193 | 2026-06-18 | Merge remote-tracking branch 'origin/main' into codex/agentic-sdlc-pipeline-adapter-plan |
| 9cfaedce480f322624803707dd28ef6993e0b602 | 9cfaedce480f322624803707dd28ef6993e0b602 | 2026-06-18 | feat: add runtime adapter for pipeline skills |
| 41fa60f8b0943e927a374eae1e868cf72a5ae3a8 | 41fa60f8b0943e927a374eae1e868cf72a5ae3a8 | 2026-06-18 | feat(hooks): deterministic completion-claim guard (Stop hook) |
| 54f714a003b63f716dca3ff6ee9e8bce4332d485 | 54f714a003b63f716dca3ff6ee9e8bce4332d485 | 2026-06-18 | test(procedure-eval): credit dispatch-strategy when work is actually delegated |
| 0aa319b279d786533ef213537d33bc454ce441a5 | 0aa319b279d786533ef213537d33bc454ce441a5 | 2026-06-18 | test(procedure-eval): drop self-referential entry skill from required_skills |
| e2672ce9eccc254ca2d26d5d303cff8e63beccf1 | e2672ce9eccc254ca2d26d5d303cff8e63beccf1 | 2026-06-18 | test(procedure-eval): credit agent dispatch as satisfying a gate skill |
| 52619c8509446a88ff1db3bc3c78c1802dbd3d43 | 52619c8509446a88ff1db3bc3c78c1802dbd3d43 | 2026-06-17 | test(evals): natural-language triggers, majority-vote default, honest matrix docs |
| a7f3476e88d3b45156a628a76eca4de541c3fe34 | a7f3476e88d3b45156a628a76eca4de541c3fe34 | 2026-06-17 | docs: rewrite README and docs/ guides with verified component analysis |
| 9357ec922b0b531a54741100f55a1b483e9a2e2a | 9357ec922b0b531a54741100f55a1b483e9a2e2a | 2026-06-17 | chore: add .gitattributes to enforce LF line endings |
| 6b9835ed828187d08bc517b97dfb36450d1bf13e | 6b9835ed828187d08bc517b97dfb36450d1bf13e | 2026-06-17 | docs(readme): link CONTRIBUTORS and credit Claude Code |
| d94baf938171a788872fd83999cddc891f9edb09 | d94baf938171a788872fd83999cddc891f9edb09 | 2026-06-17 | docs: add CONTRIBUTORS (credit maintainer + Claude) |
| aec290d09b2fcd62d09ec3d5965376b2ac8306ac | aec290d09b2fcd62d09ec3d5965376b2ac8306ac | 2026-06-17 | chore(gitignore): scope test eval-output ignores explicitly |
| c6ff27cfc9533b87a46cd1a0f3df140ccf473327 | c6ff27cfc9533b87a46cd1a0f3df140ccf473327 | 2026-06-17 | refactor(skills): rename 12 skills to descriptive, collision-free names |
| 24016a34173bc959bdcd65b59d959101938fb773 | 24016a34173bc959bdcd65b59d959101938fb773 | 2026-06-17 | chore: bump version to 0.2.7 |
| 5a01bed1458b24a6e792304a3eadce684748b97d | 5a01bed1458b24a6e792304a3eadce684748b97d | 2026-06-17 | test: add all-skill trigger matrix |
| 60a536fa181d0fda76537ad19eb5c66107c2313f | 60a536fa181d0fda76537ad19eb5c66107c2313f | 2026-06-17 | revert: track tests/ code and evals; ignore only artifacts |
| 507670f27a1c0c066c340087c7c2e8a9e5d67157 | 507670f27a1c0c066c340087c7c2e8a9e5d67157 | 2026-06-17 | chore: ignore tests/ and remove from tracking |
| a6ff92dfb025d413695c3c9fa045ee55c7e7349c | a6ff92dfb025d413695c3c9fa045ee55c7e7349c | 2026-06-17 | chore: bump version to 0.2.6 |
| bda38875271a3ff1f796ff63e48cd6936a097ebb | bda38875271a3ff1f796ff63e48cd6936a097ebb | 2026-06-17 | fix: stabilize claude spec-flow trigger |
| 8d4db40a2f22528d5a70aab54939ef8d962fa497 | 8d4db40a2f22528d5a70aab54939ef8d962fa497 | 2026-06-17 | chore: bump version to 0.2.5 |
| 4d6db93ed92f7ab7a8b9c73e9ac661e2eece8a3a | 4d6db93ed92f7ab7a8b9c73e9ac661e2eece8a3a | 2026-06-17 | test: split codex trigger eval harness |
| e34208243b6b752dcaa12b239b12b55c346dd7dc | e34208243b6b752dcaa12b239b12b55c346dd7dc | 2026-06-17 | chore: bump version to 0.2.4 |
| e378476e6cff2908365760d1c63926c1b6d60c67 | e378476e6cff2908365760d1c63926c1b6d60c67 | 2026-06-17 | test: add safe trigger smoke mode |
| 7edad23837a4840f22316ef863690e35a5ae69c3 | 7edad23837a4840f22316ef863690e35a5ae69c3 | 2026-06-17 | chore: bump version to 0.2.3 |
| 6f100b1e534862c4b6229929bb67019858d9b445 | 6f100b1e534862c4b6229929bb67019858d9b445 | 2026-06-17 | fix: standardize skill runtime roots |
| f3dd9d466dffed1b017ee90e6b7ad413c37c0d3e | f3dd9d466dffed1b017ee90e6b7ad413c37c0d3e | 2026-06-17 | chore: bump version to 0.2.2 |
| 974a917bb4502d3666611dc2d3cc829f0487392c | 974a917bb4502d3666611dc2d3cc829f0487392c | 2026-06-17 | feat: adapt dev flow for codex runtime |
| 8b9987c9ac33c8790678abec402b61df8eb6e782 | 8b9987c9ac33c8790678abec402b61df8eb6e782 | 2026-06-17 | chore: bump version to 0.2.1 |
| f1cc38251dc26a4ae59a0eb8f28ac9263a33d719 | f1cc38251dc26a4ae59a0eb8f28ac9263a33d719 | 2026-06-17 | feat: define spec plan runtime bindings |
| ac4ed4726355ec236448332233ea6966fee8f93b | ac4ed4726355ec236448332233ea6966fee8f93b | 2026-06-17 | chore: bump version to 0.2.0 |
| 57b025f0add52871ee6b017def0310c3fb864b55 | 57b025f0add52871ee6b017def0310c3fb864b55 | 2026-06-17 | chore: remove ci workflow |
| ee0ff5b36daeb17ec9e0d2138f5c0b1c4509d2cb | ee0ff5b36daeb17ec9e0d2138f5c0b1c4509d2cb | 2026-06-17 | feat: add agentic sdlc router flows |
| 0d90fdca994f12d7cd530e5f5dcbc7938513b2b1 | 0d90fdca994f12d7cd530e5f5dcbc7938513b2b1 | 2026-06-17 | refactor: move rules to skill contracts |
| 09e363583d3d6e199461a0667137809ae61bcbfb | 09e363583d3d6e199461a0667137809ae61bcbfb | 2026-06-17 | chore: update plugin owner metadata |
| 754d0256f9c45facdb525421d6ae5fd564ba7445 | 754d0256f9c45facdb525421d6ae5fd564ba7445 | 2026-06-17 | docs: describe claude plugin components |
| cb33fd02182c3a40a0dbd21dbc9f9ddede562f2e | cb33fd02182c3a40a0dbd21dbc9f9ddede562f2e | 2026-06-17 | docs: keep gate comments platform neutral |
| d97ba3ca48ba46dc470be24933a092c7efc56a10 | d97ba3ca48ba46dc470be24933a092c7efc56a10 | 2026-06-17 | ci: use node24 compatible actions |
| 20441c8ad2f0f20bf30437c7e4ba68e65b6ed06b | 20441c8ad2f0f20bf30437c7e4ba68e65b6ed06b | 2026-06-17 | chore: bootstrap agentic sdlc plugin |
