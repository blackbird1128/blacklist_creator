
CONSTRUCTIVISATION_DIR ?= ../geocoq_constructivisation_result
CONS_THEORIES_DIR ?= $(CONSTRUCTIVISATION_DIR)/theories

POST_CONSTRUCTIVISATION_DIR ?= ../post_constructivisation_result/
POST_CONS_THEORIES_DIR ?= $(POST_CONSTRUCTIVISATION_DIR)/theories

constructivisation_in.txt: constructivisation_pairs.txt
	cut -d " " -f 1 $< > $@

project_sorted_files.txt: $(CONSTRUCTIVISATION_DIR)/_CoqProject Makefile
	rocq dep -f $< -sort | tr " " "\n" | grep -o "theories/.*" > $@

post_project_sorted_files.txt: $(POST_CONSTRUCTIVISATION_DIR)/_CoqProject Makefile
	ordered_files=$$(cd "$(POST_CONSTRUCTIVISATION_DIR)" && rocq dep -f _CoqProject -sort) && \
	printf '%s\n' "$$ordered_files" | tr ' ' '\n' | sed '/^$$/d' > "$@"

constructivisation_in_sorted.txt: project_sorted_files.txt constructivisation_in.txt
	awk 'NR==FNR {order[$$0]=NR; next} ($$1 in order) {print order[$$1], $$0}' $^ \
	| sort -n \
	| cut -d' ' -f2- > $@

post_blacklist.logs: post_project_sorted_files.txt
	@set -e; \
	mkdir -p post_logs; \
	find post_logs -type f -name '*.logs' -delete; \
	while IFS= read -r rel; do \
		file="$(POST_CONSTRUCTIVISATION_DIR)/$$rel"; \
		if grep -qF 'blacklister-original-terminator:' "$$file"; then \
			tmp="$$file.blacklist"; \
			printf 'Post blacklisting %s\n' "$$file"; \
			python3 blacklister.py --post --theories-dir "$(POST_CONS_THEORIES_DIR)" \
				--workers "$${NUM_CORES:-5}" --log-file "post_logs/$${rel%.v}.logs" "$$file" > "$$tmp"; \
			mv "$$tmp" "$$file"; \
		fi; \
		rocq c -Q "$(POST_CONS_THEORIES_DIR)" GeoCoq -w -ambiguous-paths -w notation-overridden "$$file"; \
	done < "$<"; \
	find post_logs -type f -name '*.logs' -exec cat {} + > "$@.tmp"; \
	mv "$@.tmp" "$@"

blacklist.logs: project_sorted_files.txt
	@set -e; \
	mkdir -p logs; \
	rm -f logs/*.logs; \
	while IFS= read -r rel; do \
		file="$(CONSTRUCTIVISATION_DIR)/$$rel"; \
		tmp="$$file.blacklist"; \
		printf 'Processing %s\n' "$$file"; \
		if rocq c -Q $(CONS_THEORIES_DIR) GeoCoq -w -ambiguous-paths -w notation-overridden "$$file" > /dev/null; then \
			printf 'Already compiles, skipping blacklist for %s\n' "$$file"; \
			continue; \
		fi; \
		python3 blacklister.py --theories-dir "$(CONS_THEORIES_DIR)" --workers 5 "$$file" > "$$tmp"; \
		mv "$$tmp" "$$file"; \
		if ! rocq c -Q $(CONS_THEORIES_DIR) GeoCoq -w -ambiguous-paths -w notation-overridden "$$file" > /dev/null; then \
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
