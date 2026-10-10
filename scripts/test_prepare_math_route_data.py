"""Offline checks for label auditing and group leakage in the math dataset export."""
from copy import deepcopy

from prepare_math_route_data import assign_folds, label_for


def main():
    cap = {
        "labelUsable": True, "attempts": 3, "gradableAttempts": 3,
        "localSuccessCount": 3, "localSuccessRate": 1.0, "runtime": {"completed": 3},
        "attemptDetails": [{"runId": str(i), "runtimeStatus": "completed", "mathVerdict": "correct"}
                           for i in range(3)],
    }
    assert label_for(cap)[0] == "local"
    unsafe = deepcopy(cap)
    unsafe["attemptDetails"][0]["mathVerdict"] = "incorrect"
    unsafe.update(localSuccessCount=2, localSuccessRate=0.6666667)
    assert label_for(unsafe)[0] == "online"
    inconsistent = deepcopy(unsafe)
    inconsistent["localSuccessRate"] = 1.0
    assert label_for(inconsistent)[0] is None
    cap["labelUsable"] = False
    assert label_for(cap)[0] is None
    truncated = deepcopy(unsafe)
    truncated["runtime"] = {"completed": 2, "truncated": 1}
    truncated["attemptDetails"][0]["runtimeStatus"] = "truncated"
    assert label_for(truncated)[0] == "online"
    rows = [{"questionId": str(i), "groupId": str(i), "label": "online" if i < 20 else "local",
             "mathType": "functions"} for i in range(240)]
    assignment = assign_folds(rows, 42)
    assert assignment == assign_folds(list(rows), 42)
    for fold in range(5):
        assert sum(assignment[row["questionId"]] == fold for row in rows) == 48
        assert sum(assignment[row["questionId"]] == fold for row in rows[:20]) == 4
    rows[1]["groupId"] = rows[0]["groupId"]
    assignment = assign_folds(rows, 42)
    assert assignment["0"] == assignment["1"]
    print("math dataset checks passed")


if __name__ == "__main__":
    main()
