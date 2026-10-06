@echo off
cd /d "%~dp0"
title Fraud Detection Engine - leave this window open during the demo
python -m streamlit run app.py --server.port 8501
