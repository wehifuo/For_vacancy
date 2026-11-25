import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import enrich_companies as enrich
from db import CompanyStatus


def test_empty_payload_is_parsing_failed():
    assert enrich.decide_status({}) == CompanyStatus.PARSING_FAILED


def test_incomplete_address():
    payload = {
        "company_name": "ACME",
        "postal_address": {
            "postcode": "10115",
            "city": "Berlin",
            "street": "",
            "house_no": "",
        },
    }
    assert enrich.decide_status(payload) == CompanyStatus.ADDRESS_INCOMPLETE


def test_complete_address_is_ok():
    payload = {
        "company_name": "ACME",
        "postal_address": {
            "postcode": "10115",
            "city": "Berlin",
            "street": "Main Street",
            "house_no": "12",
        },
    }
    assert enrich.decide_status(payload) == CompanyStatus.OK


def test_postal_address_join():
    address = {
        "street": "Main Street",
        "house_no": "12",
        "postcode": "10115",
        "city": "Berlin",
        "country": "Germany",
    }
    assert enrich.build_postal_address(address) == (
        "Main Street 12, 10115 Berlin, Germany"
    )


def test_has_any_value():
    assert enrich.has_any_value({}) is False
    assert enrich.has_any_value({"company_name": None}) is False
    assert enrich.has_any_value({"company_name": "ACME"}) is True


def test_email_validation():
    assert enrich._email("ce@baroloandchampagne.com") == (
        "ce@baroloandchampagne.com"
    )
    assert enrich._email("[email protected]") is None
    assert enrich._email("") is None
