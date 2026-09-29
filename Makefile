
CONSTRUCTIVISATION_DIR ?= ../geocoq_constructivisation_result
THEORIES_DIR ?= $(CONSTRUCTIVISATION_DIR)/theories

constructivisation_in.txt: constructivisation_pairs.txt
	cut -d " " -f 1 $< > $@

project_sorted_files.txt: ../geocoq_constructivisation_result/_CoqProject
	rocq dep -f $< -sort | tr " " "\n" | grep -o "theories/.*" > $@

constructivisation_in_sorted.txt: project_sorted_files.txt constructivisation_in.txt
	awk 'NR==FNR {order[$$0]=NR; next} ($$1 in order) {print order[$$1], $$0}' $^ \
	| sort -n \
	| cut -d' ' -f2- > $@

blacklist.logs: project_sorted_files.txt
	@set -e; \
	mkdir -p logs; \
	rm -f logs/*.logs; \
	while IFS= read -r rel; do \
		file="$(CONSTRUCTIVISATION_DIR)/$$rel"; \
		tmp="$$file.blacklist"; \
		printf 'Processing %s\n' "$$file"; \
		if rocq c -Q $(THEORIES_DIR) GeoCoq -w -ambiguous-paths -w notation-overridden "$$file" > /dev/null; then \
			printf 'Already compiles, skipping blacklist for %s\n' "$$file"; \
			continue; \
		fi; \
		python3 blacklister.py --theories-dir "$(THEORIES_DIR)" --workers 18 "$$file" > "$$tmp"; \
		mv "$$tmp" "$$file"; \
		if ! rocq c -Q $(THEORIES_DIR) GeoCoq -w -ambiguous-paths -w notation-overridden "$$file" > /dev/null; then \
			printf 'rocq failed on %s\n' "$$file" >&2; \
		fi; \
	done < $<; \
	find logs -type f -name '*.logs' -exec cat {} + > $@

blacklist_without_stab_err.logs: blacklist.logs
	awk '\
	/^[[:space:]]*[^:]+: File ".*", line [0-9]+, characters [0-9]+-[0-9]+:$$/ {\
		header = $$0;\
		if (getline err) {\
			if (err ~ /^[[:space:]]*Error: Tactic failure: Could not deduce the stability of the goal.*\.$$/)\
				next;\
			print header;\
			print err;\
			next;\
		}\
		print header;\
		next;\
	}\
	{ print }' $< > $@

clean:
	rm -f constructivisation_in.txt
	rm -f project_sorted_files.txt
	rm -f blacklist.logs
	rm -f blacklist_without_stab_err.logs
