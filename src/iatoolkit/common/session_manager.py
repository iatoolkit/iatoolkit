# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from flask import session

class SessionManager:
    @staticmethod
    def set(key, value):
        session[key] = value

    @staticmethod
    def get(key, default=None):
        return session.get(key, default)

    @staticmethod
    def remove(key):
        if key in session:
            session.pop(key)

    @staticmethod
    def clear():
        session.clear()
