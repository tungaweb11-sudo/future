cat > full_fix.sh << 'SCRIPT_END'
#!/bin/bash

echo "========================================="
echo "  Winner Predict - FULL FIX SCRIPT      "
echo "========================================="

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Step 1: Check Python 3.11
echo -e "${YELLOW}Step 1: Checking Python 3.11...${NC}"
if ! command -v python3.11 &> /dev/null; then
	echo -e "${RED}Python 3.11 not found. Installing...${NC}"
	sudo apt update
	sudo apt install -y wget build-essential libssl-dev zlib1g-dev \
	libbz2-dev libreadline-dev libsqlite3-dev curl \
	libncursesw5-dev xz-utils tk-dev libxml2-dev libxmlsec1-dev \
	libffi-dev liblzma-dev
	
	cd /tmp
	wget https://www.python.org/ftp/python/3.11.9/Python-3.11.9.tgz
	tar -xzf Python-3.11.9.tgz
	cd Python-3.11.9
	./configure --enable-optimizations
	make -j$(nproc)
	sudo make altinstall
	else
		echo -e "${GREEN}✅ Python 3.11 found${NC}"
		fi
		
		# Step 2: Create virtual environment
		echo -e "${YELLOW}Step 2: Creating virtual environment...${NC}"
		cd ~/Desktop/"winner predict"
		rm -rf .venv
		python3.11 -m venv .venv
		source .venv/bin/activate
		
		# Step 3: Install dependencies
		echo -e "${YELLOW}Step 3: Installing dependencies...${NC}"
		cd backend
		
		# Create requirements.txt using echo commands
		echo "Flask==3.0.3" > requirements.txt
		echo "flask-cors==4.0.1" >> requirements.txt
		echo "tensorflow==2.15.0" >> requirements.txt
		echo "numpy==1.24.3" >> requirements.txt
		echo "pandas==2.1.4" >> requirements.txt
		echo "scikit-learn==1.3.2" >> requirements.txt
		echo "matplotlib==3.8.2" >> requirements.txt
		echo "joblib==1.3.2" >> requirements.txt
		echo "requests==2.31.0" >> requirements.txt
		echo "python-dotenv==1.0.0" >> requirements.txt
		
		echo -e "${YELLOW}Requirements.txt created:${NC}"
		cat requirements.txt
		
		pip install --upgrade pip
		pip install -r requirements.txt
		
		# Step 4: Verify installation
		echo -e "${YELLOW}Step 4: Verifying installation...${NC}"
		python -c "
		import sys
		print('Python version:', sys.version)
		try:
		import tensorflow as tf
		print('✅ TensorFlow:', tf.__version__)
		except Exception as e:
		print('❌ TensorFlow failed:', e)
		try:
		import numpy as np
		print('✅ NumPy:', np.__version__)
		except Exception as e:
		print('❌ NumPy failed:', e)
		try:
		import sklearn
		print('✅ Scikit-learn:', sklearn.__version__)
		except Exception as e:
		print('❌ Scikit-learn failed:', e)
		try:
		import pandas as pd
		print('✅ Pandas:', pd.__version__)
		except Exception as e:
		print('❌ Pandas failed:', e)
		"
		
		# Step 5: Train model
		echo -e "${YELLOW}Step 5: Training model...${NC}"
		python -m training.train_model
		
		echo -e "${GREEN}=========================================${NC}"
		echo -e "${GREEN}✅ Setup complete!${NC}"
		echo -e "${GREEN}=========================================${NC}"
		SCRIPT_END
		
		# Make it executable and run
		chmod +x full_fix.sh
		./full_fix.sh
