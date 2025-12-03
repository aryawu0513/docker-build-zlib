## Interactive Bash / Docker Setup

Launch an interactive bash session inside the container:
```bash
./docker-build.sh
podman run -it --rm -v $PWD/zlib:/zlib build-zlib /bin/bash
```
Verify that the build works:
```bash
make
ls /usr/lib/x86_64-linux-gnu/libz.so*
ls /usr/include/zlib.h
ls /unity
```
Compile and run one of the provided example programs that include a main function:
```bash
make test/example #(same as gcc -I/usr/include test/example.c -lz -o test/example)
./test/example
```


## Key Facts About zlib
	•	zlib is a library, not a set of standalone programs like coreutils.
	•	Most source files (e.g., crc32.c, deflate.c, gzwrite.c) compile into object files (.o) and are linked into libz.a or libz.so.
	•	These source files do not contain a main() function, so they cannot be executed directly.
	•	The only executables provided are small examples such as example, minigzip, etc.

Implication: To test or use zlib like we do with coreutils, we need to:
	1.	Write our own test programs or example programs that include zlib headers and call its functions.
	2.	Compile these programs while linking against the zlib library (libz.a or libz.so).

Essentially, zlib’s workflow requires creating a user program that consumes the library, rather than running the library files directly.


Why example.c Can Call Many Functions
    Even though example.c does not include source files like gzwrite.c directly, it can call functions such as gzputc() because:
	1.	Header inclusion: example.c includes zlib.h: 
        #include "zlib.h"
        This provides declarations for all zlib functions:
        int gzputc(gzFile file, int c);

	2.	Linking with the library: The Makefile links example.o against the compiled zlib objects:
        example$(EXE): example.o $(STATICLIB)
            $(CC) $(CFLAGS) $(LDFLAGS) -o $@ example.o $(TEST_LIBS)

        Here:
            •	example.o is the compiled object for example.c.
            •	$(STATICLIB) is libz.a, which contains all the compiled object files: gzread.o, gzwrite.o, deflate.o, etc.

        The linker resolves function calls like gzputc() from libz.a.


## Creating Unity Test Harnesses for zlib

To test individual zlib modules using the Unity testing framework:
	1.	Create a test file for each module you want to test (e.g., test/test_gzread.c).
	2.	Add Makefile rules to build and link the test program with zlib and Unity:

Pattern rule for test harnesses
tests_%: tests_%.o $(STATICLIB) unity.o
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $< $(STATICLIB) unity.o

Build the object for a test harness in test/
tests_%.o: $(SRCDIR)test/tests_%.c $(SRCDIR)zlib.h zconf.h
	$(CC) $(CFLAGS) $(ZINCOUT) -c -o $@ $<

Notes:
	•	$< refers to the .o file of the test source.
	•	$(STATICLIB) ensures that all zlib object files are linked.
	•	unity.o links in the Unity testing framework functions.

This approach lets us create multiple test_xxx programs that behave like example.c

eg.
make test_gzread
./test_gzread

## We do it for all the .c file in /zlib.
None of them have a main() function.
Not the ones in /examples. those are programs that demonstrate how to use zlib. (these are the ones that have a main function)

We do it per function.
But problem: most functions in the source code is declared local via the ZLIB_INTERNAL attribute, making it invisible outside its compilation unit and therefore unavailable to our test harness. 

To address this, we created a small wrapper function, test_gz_avail, that simply calls gz_avail and is globally visible. We then modified our test code to call test_gz_avail instead of gz_avail.
```c
int test_gz_avail(gz_statep state) { return gz_avail(state); }
```
TO see that its global scope: 
```bash
nm libz.a | grep gz_avail
0000000000000090 t gz_avail
0000000000000910 T test_gz_avail
```