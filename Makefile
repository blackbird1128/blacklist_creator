
.PHONY: all

CONSTRUCTIVE_DIR := ../constructivisation_result/theories/Constructive
THEORIES_DIR := ../constructivisation_result/theories
SOURCES_FILE := files.txt
SOURCES_REL := $(shell cat $(SOURCES_FILE))
SOURCES := $(addprefix ../constructivisation_result/,$(SOURCES_REL))

all: blacklist.logs

blacklist.logs: $(SOURCES_FILE) $(SOURCES)
	@set -e; \
	mkdir -p logs; \
	rm -f logs/*.logs; \
	for file in $(SOURCES); do \
		tmp="$$file.blacklist"; \
		printf 'Processing %s\n' "$$file"; \
		if rocq c -Q $(THEORIES_DIR) GeoCoq -w -ambiguous-paths -w notation-overridden "$$file" > /dev/null; then \
			printf 'Already compiles, skipping blacklist for %s\n' "$$file"; \
			continue; \
		fi; \
		python3 blacklister.py --workers 12 "$$file" > "$$tmp"; \
		mv "$$tmp" "$$file"; \
		if ! rocq c -Q $(THEORIES_DIR) GeoCoq -w -ambiguous-paths -w notation-overridden "$$file" > /dev/null; then \
			printf 'rocq failed on %s\n' "$$file" >&2; \
		fi; \
	done; \
	cat logs/*.logs > $@

clean:
	rm -f blacklist.logs
	rm -f logs/*.logs
