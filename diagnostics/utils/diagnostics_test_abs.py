# -*- coding: utf-8 -*-
from abc import ABCMeta, abstractmethod

__all__ = ["DiagnosticsTestAbs"]


class NotSupportedException(Exception):
    """To be raised when a test is not supported for local or robot"""
    pass


class DiagnosticsTestAbs(metaclass=ABCMeta):
    name = None

    @staticmethod
    @abstractmethod
    def run_local(shell, args, parsed):
        pass

    @staticmethod
    @abstractmethod
    def run_robot(shell, args, parsed):
        pass

    @staticmethod
    def _dt_test_fingerprint():
        return True
