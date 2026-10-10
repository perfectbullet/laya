"""Weight-free checks for balancing, grouped splits, and historical routing denominators."""
from prepare_math_route_data import assign_folds
from train_math_difficulty import LABELS, QUESTIONS, balanced, filter_excluded, final_rows, metrics
from collections import Counter

rows = [{"questionId": "%s-%d" % (label, i), "state": "question-%s-%d" % (label, i),
         "questions": QUESTIONS, "expected": {"math_difficulty": label}}
        for label, count in zip(LABELS, (10, 20, 30)) for i in range(count)]
expanded = balanced(rows, 7)
assert Counter(r["expected"]["math_difficulty"] for r in expanded) == dict.fromkeys(LABELS, 30)
assert {r["questionId"] for r in expanded} == {r["questionId"] for r in rows}
assert balanced(rows, 7) == expanded
final = final_rows(rows, 7)
assert final["calibration"] == [] and final["test"] == rows
assert {r["questionId"] for r in final["train"]} == {r["questionId"] for r in rows}
assert Counter(r["expected"]["math_difficulty"] for r in final["train"]) == dict.fromkeys(LABELS, 30)
kept, excluded = filter_excluded([{"questionId": "a", "label": "simple"},
                                 {"questionId": "b", "label": "difficult"}], ["b"])
assert [r["questionId"] for r in kept] == ["a"]
assert excluded == [{"questionId": "b", "label": "difficult", "reason": "explicit_input_length_exclusion"}]
try:
    filter_excluded(kept, ["unknown"])
except ValueError:
    pass
else:
    raise AssertionError("unknown exclusion must fail")
groups = [{"questionId": r["questionId"], "label": r["expected"]["math_difficulty"],
           "groupId": r["questionId"], "mathType": "algebra"} for r in rows]
groups.append(dict(groups[0], questionId="duplicate", groupId=groups[0]["groupId"]))
folds = assign_folds(groups, 7)
assert folds["duplicate"] == folds[groups[0]["questionId"]]
samples = [{"questionId": "a", "gold": "simple", "choice": "simple"},
           {"questionId": "b", "gold": "medium", "choice": "medium"},
           {"questionId": "c", "gold": "difficult", "choice": "medium"}]
audit = {"a": {"localEvaluation": {"correct": 2, "review": 1}},
         "b": {"localEvaluation": {"correct": 2, "incorrect": 1}}, "c": {"localEvaluation": {}}}
report = metrics(samples, audit)
assert report["accuracy"] == 2 / 3
assert report["policies"]["simple_medium"]["unevaluatedLocalQuestions"] == 1
assert report["policies"]["simple_medium"]["resolvedAttemptErrorRate"] == 1 / 5
assert report["policies"]["simple_only"]["attemptVerdicts"]["review"] == 1
print("math difficulty checks passed")
