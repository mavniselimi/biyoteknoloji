# -*- coding: utf-8 -*-
"""Offline tests for the ingestion package (WP-04).

Every test in this package runs without a socket. The acquisition path is
written against an injected transport, so a scripted fake is enough to exercise
retry, caching, pagination and completeness end to end.
"""
