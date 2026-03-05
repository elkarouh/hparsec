# Makefile for Nim parser projects

NIM = nim
NIMFLAGS = -d:release
NIM_FILES = $(wildcard *.nim)
NIM_BINS = $(NIM_FILES:.nim=)

.PHONY: all build run clean check debug test version

# Build all Nim files
all: build

build: $(NIM_BINS)

# Pattern rule: compile each .nim file to binary
%: %.nim
	$(NIM) compile $(NIMFLAGS) -o:$@ $<

# Run all binaries
run: $(NIM_BINS)
	@for bin in $(NIM_BINS); do \
		echo "=== Running $$bin ==="; \
		./$$bin || true; \
		echo ""; \
	done

# Build and run in one step
compile-run:
	@for src in $(NIM_FILES); do \
		echo "=== Compiling and running $$src ==="; \
		$(NIM) compile --run $(NIMFLAGS) $$src || true; \
		echo ""; \
	done

# Debug build
debug: $(NIM_FILES)
	@for src in $(NIM_FILES); do \
		base=$$(basename $$src .nim); \
		$(NIM) compile -d:debug -o:$${base}_debug $$src; \
	done

# Run debug binaries
run-debug:
	@for src in $(NIM_FILES); do \
		base=$$(basename $$src .nim); \
		echo "=== Running $${base}_debug ==="; \
		./$${base}_debug || true; \
	done

# Type check only
check:
	@for src in $(NIM_FILES); do \
		echo "Checking $$src..."; \
		$(NIM) check $$src; \
	done

# Clean all binaries and cache
clean:
	rm -f $(NIM_BINS) $(NIM_BINS:=_debug)
	rm -rf nimcache/

# Rebuild from scratch
rebuild: clean build

# Run tests (same as run)
test: run

# Show Nim version
version:
	$(NIM) --version

# Show all targets
help:
	@echo "Available targets:"
	@echo "  all/build     - Build all Nim files (default)"
	@echo "  run           - Run all binaries"
	@echo "  compile-run   - Compile and run each file in one step"
	@echo "  debug         - Build debug versions"
	@echo "  run-debug     - Run debug binaries"
	@echo "  check         - Type check only"
	@echo "  clean         - Remove binaries and nimcache/"
	@echo "  rebuild       - Clean and rebuild"
	@echo "  test          - Run tests"
	@echo "  version       - Show Nim version"
	@echo "  help          - Show this help"

# List discovered files
files:
	@echo "Nim files found: $(NIM_FILES)"
	@echo "Binaries to build: $(NIM_BINS)"
