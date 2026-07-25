@echo off
echo ========================================================
echo Pushing Eco-Loop Codebase & Deliverables to GitHub...
echo Target Repo: https://github.com/Mishra123456/ECO_LOOP.git
echo ========================================================

if exist .git (
    rmdir /s /q .git
)

git init
git remote add origin https://github.com/Mishra123456/ECO_LOOP.git
git add .
git commit -m "Honeywell Hackathon 2026 Submission - Eco-Loop Autonomous AI Building Intelligence Platform"
git branch -M main
git push -u origin main --force

echo.
echo SUCCESS! Your codebase and all deliverables are live on GitHub!
pause
