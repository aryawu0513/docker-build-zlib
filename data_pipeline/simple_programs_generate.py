
from test_gpt5_generation import generate_tests_for_one_zlib_file

default_progs = [
    "adler32.c",
    "compress.c",
    "crc32.c",
    "deflate.c",
    "gzclose.c",
    "gzlib.c",
    "gzread.c",
    "gzwrite.c",
    "infback.c",
    "inffast.c",
    "inflate.c",
    "inftrees.c",
    "trees.c",
    "uncompr.c",
    "zutil.c"
]

if __name__ == "__main__":
    success = 0
    failed = 0
    print(len(default_progs), " files to generate tests for.")
    for i, program_name in enumerate(default_progs, 1):
        program_name = program_name.split(".")[0] #eg. "pwd"
        print(f"\n{'='*70}")
        print(f"Generating tests for zlib files: {program_name}")
        print(f"[{i}/{len(default_progs)}] {program_name}")
        print('='*70)
        try:
            generate_tests_for_one_zlib_file(program_name)
            success += 1
            print(f"✓ {program_name} DONE")
        except Exception as e:
            failed += 1
            print(f"✗ {program_name} FAILED: {e}")
            continue  # Keep going to next program
    print(f"\n{'='*70}")
    print(f"SUMMARY: {success} success, {failed} failed")
    print('='*70)