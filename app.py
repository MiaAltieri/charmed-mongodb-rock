# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.
from typing import Any
from flask import Flask, request, jsonify
import logging
import base64
from pydantic import BaseModel, TypeAdapter
import os

# Default to 1 year
YEAR = 31_556_952
GRACE_PERIOD: int = int(os.getenv("GRACE_PERIOD_SECONDS", YEAR))


class Patch(BaseModel):
    op: str
    path: str = "/spec/template/spec/terminationGracePeriodSeconds"
    value: int


app = Flask(__name__)

webhook = logging.getLogger(__name__)
webhook.setLevel(logging.INFO)
logging.basicConfig(format="[%(asctime)s] %(levelname)s: %(message)s")

ADAPTER = TypeAdapter(list[Patch])


def patch_termination(existing_value: bool) -> str:
    op = "replace" if existing_value else "add"
    webhook.info(f"Updating terminationGracePeriodSeconds, replacing it ({op = })")
    patch_operations = [
        Patch(
            op=op,
            value=GRACE_PERIOD,
        )
    ]
    return base64.b64encode(ADAPTER.dump_json(patch_operations)).decode()


def admission_review(uid: str, message: str, existing_value: bool) -> dict:
    print("admission_review - existing_value", existing_value)
    if existing_value:
        return {
            "apiVersion": "admission.k8s.io/v1",
            "kind": "AdmissionReview",
            "response": {
                "uid": uid,
                "allowed": True,
                "patchType": "JSONPatch",
                "status": {"message": message},
                "patch": patch_termination(existing_value),
            },
        }
    return {
        "apiVersion": "admission.k8s.io/v1",
        "kind": "AdmissionReview",
        "response": {
            "uid": uid,
            "allowed": True,
            "status": {"message": "No value provided, continue."},
        },
    }


def admission_validation(uid: str, current_value: int | None):
    if not current_value or current_value > 30:
        print("current value", current_value)
        return {
            "apiVersion": "admission.k8s.io/v1",
            "kind": "AdmissionReview",
            "response": {
                "uid": uid,
                "allowed": True,
                "status": {"message": f"Valid value has been provided ({current_value})"},
            },
        }
    return {
        "apiVersion": "admission.k8s.io/v1",
        "kind": "AdmissionReview",
        "response": {
            "uid": uid,
            "allowed": False,
            "status": {
                "code": 403,
                "message": f"Termination period lower than 30s is not allowed (given {current_value})",
            },
        },
    }


@app.route("/mutate", methods=["POST"])
def mutate_request():
    req = request.get_json()
    uid = req["request"]["uid"]
    selector = req["request"]["object"]["spec"]["template"]["spec"]

    return jsonify(
        admission_review(
            uid,
            "Successfully updated terminationGracePeriodSeconds.",
            True if "terminationGracePeriodSeconds" in selector else False,
        )
    )


@app.route("/validate", methods=["POST"])
def validate_request():
    req = request.get_json()
    uid = req["request"]["uid"]
    selector = req["request"]["object"]["spec"]["template"]["spec"]
    period_value = selector.get("terminationGracePeriodSeconds")

    return jsonify(admission_validation(uid, period_value))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
