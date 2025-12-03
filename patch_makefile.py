#!/usr/bin/env python3
import re

makefile_in = "Makefile"
makefile_out = "Makefile"

with open(makefile_in) as f:
    content = f.read()

# Define the exact blocks to match (with the commands)
example_o_block = r"""example\.o: \$\(SRCDIR\)test/example\.c \$\(SRCDIR\)zlib\.h zconf\.h
\t\$\((CC|CFLAGS).*\) -c -o \$@ \$\(SRCDIR\)test/example\.c"""

example_exe_block = r"""example\$\((EXE)\): example\.o \$\(STATICLIB\)
\t\$\((CC|CFLAGS).*\) -o \$@ example\.o \$\(TEST_LIBS\)"""

# Text to insert after each block
insert_after_example_o = """\n# Build the object for a test harness in test/
tests_%.o: $(SRCDIR)tests/tests_%.c $(SRCDIR)zlib.h zconf.h
\t$(CC) $(CFLAGS) $(ZINCOUT) -c -o $@ $<"""

insert_after_example_exe = """\n# Pattern rule for test harnesses
tests_%: tests_%.o $(STATICLIB) unity/unity.o
\t$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $< $(STATICLIB) unity/unity.o"""

# Function to insert text after a matched block
def insert_after_block(pattern, text, content):
    return re.sub(pattern, lambda m: m.group(0) + "\n" + text, content, flags=re.MULTILINE)

# Apply insertions
content = insert_after_block(example_o_block, insert_after_example_o, content)
content = insert_after_block(example_exe_block, insert_after_example_exe, content)

# Write new Makefile
with open(makefile_out, "w") as f:
    f.write(content)