"""Tests default to an isolated database, never office credentials."""
import os

os.environ['APP_ENV'] = 'development'
os.environ['AUTH_MODE'] = 'gateway'
os.environ['DATABASE_URL'] = 'sqlite://'
