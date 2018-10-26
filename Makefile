all:


bump-upload:
	$(MAKE) bump
	$(MAKE) upload

bump:
	bumpversion patch

upload:
	git push --tags
	git push
#	rm -f dist/*
#	python setup.py sdist
#	twine upload dist/*

