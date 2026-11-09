test:
	python3 zsh_linter.py
	python3 -B corpus_test.py corpus 
verbose:
	python3 -B corpus_test.py corpus -v	
