#!/bin/bash

set -e  # Exit on any error

echo "🔧 Building CHUB Frontend..."

# Build the React app
echo "📦 Building React app..."
cd frontend && npm run build && cd ..

# Create templates directory if it doesn't exist
echo "📁 Creating templates directory..."
mkdir -p templates

# Copy main SPA files
echo "📄 Copying index.html..."
cp frontend/dist/index.html templates/index.html

# Copy Vite-bundled JS/CSS
echo "⚡ Copying Vite assets..."
if [ -d "templates/assets" ]; then
    rm -rf templates/assets
fi
if [ -d "frontend/dist/assets" ]; then
    cp -r frontend/dist/assets templates/assets
    echo "   ✅ Assets copied"
else
    echo "   ⚠️  No frontend/dist/assets directory found"
fi

# Copy static public folders (icons, img, posters, etc.)
echo "🖼️  Copying static assets..."

# Icons
if [ -d "templates/icons" ]; then
    rm -rf templates/icons
fi
if [ -d "frontend/dist/icons" ]; then
    cp -r frontend/dist/icons templates/icons
    echo "   ✅ Icons copied"
elif [ -d "frontend/public/icons" ]; then
    cp -r frontend/public/icons templates/icons
    echo "   ✅ Icons copied from public"
else
    echo "   ⚠️  No icons directory found"
fi

# Images
if [ -d "templates/img" ]; then
    rm -rf templates/img
fi
if [ -d "frontend/dist/img" ]; then
    cp -r frontend/dist/img templates/img
    echo "   ✅ Images copied"
elif [ -d "frontend/public/img" ]; then
    cp -r frontend/public/img templates/img
    echo "   ✅ Images copied from public"
else
    echo "   ⚠️  No img directory found"
fi

# Posters (critical for ColorListField)
if [ -d "templates/posters" ]; then
    rm -rf templates/posters
fi
if [ -d "frontend/dist/posters" ]; then
    cp -r frontend/dist/posters templates/posters
    echo "   ✅ Posters copied"
elif [ -d "frontend/public/posters" ]; then
    cp -r frontend/public/posters templates/posters
    echo "   ✅ Posters copied from public"
else
    echo "   ❌ No posters directory found - ColorListField may not work!"
    exit 1
fi

# Verify critical files exist
echo "🔍 Verifying build..."
if [ ! -f "templates/index.html" ]; then
    echo "❌ templates/index.html missing!"
    exit 1
fi

if [ ! -d "templates/posters" ]; then
    echo "❌ templates/posters missing!"
    exit 1
fi

# Count poster files
poster_count=$(find templates/posters -name "*.jpg" -o -name "*.jpeg" -o -name "*.png" -o -name "*.webp" | wc -l)
echo "📊 Found $poster_count poster files"

if [ "$poster_count" -eq 0 ]; then
    echo "⚠️  Warning: No poster files found - ColorListField previews won't work"
fi

echo "✅ Frontend build complete!"
echo "📁 Templates directory structure:"
ls -la templates/

echo ""
echo "🚀 Ready to serve with FastAPI!"