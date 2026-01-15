"""
ATS (Applicant Tracking System) Agent Module
"""
from flask import Blueprint

ats_bp = Blueprint('ats', __name__, url_prefix='/ats')

from . import routes
