
.PHONY: all

all:
	find ../geocoq_constructivisation_result/theories/Constructive/ -name "*.v" -type f | xargs  -I {} python3 blacklister.py "{}"
	cat logs/*.logs > blacklist.logs

