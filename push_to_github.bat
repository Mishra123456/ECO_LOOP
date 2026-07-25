@echo off
echo ========================================================
echo Pushing Eco-Loop Codebase Updates to GitHub (Safe Push)
echo Target Repo: https://github.com/Mishra123456/ECO_LOOP.git
echo ========================================================

if not exist .git (
    git init
    git remote add origin https://github.com/Mishra123456/ECO_LOOP.git
)

git fetch origin
git branch -M main
git pull origin main --allow-unrelated-histories -X ours --no-edit

git add .
git commit -m "Update Eco-Loop codebase and README"
git push -u origin main

echo.
echo SUCCESS! New content and README pushed to GitHub safely!
pause
