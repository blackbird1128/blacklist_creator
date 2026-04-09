.PHONY: all clean

CONSTRUCTIVE_DIR := ../constructivisation_result/theories/Constructive
THEORIES_DIR := ../constructivisation_result/theories
SRC_MAKEFILE := ../rocq-ditto/Makefile
SOURCES_FILE := files.txt

all: blacklist.logs

files.txt: $(SRC_MAKEFILE)
	awk '\
		/^constructivisation-build:/ { in_rule = 1; next } \
		in_rule && /^[^ \t].*:/      { in_rule = 0 } \
		in_rule { \
			for (i = 1; i < NF; i++) \
				if ($$i == "-o") { \
					out = $$(i+1); \
					sub(/^\$$\(GEOCOQ_OUTPUT_DIR\)\//, "", out); \
					print out; \
				} \
		} \
	' $< > $@

blacklist.logs: files.txt
	@set -e; \
	mkdir -p logs; \
	rm -f logs/*.logs; \
	while IFS= read -r rel; do \
		file="../constructivisation_result/$$rel"; \
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
	done < $<; \
	find logs -type f -name '*.logs' -exec cat {} + > $@

clean:
	rm -f blacklist.logs files.txt
	rm -f logs/*.logs
