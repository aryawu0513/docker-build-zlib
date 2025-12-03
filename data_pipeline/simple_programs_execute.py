from test_container_one_mull import run_build_execute_mutate_for_one_zlib_program

default_progs = [
    "adler32",
    "compress",
    "crc32",
    "deflate",
    "gzclose",
    "gzlib",
    "gzread",
    "gzwrite",
    "infback",
    "inffast",
    "inflate",
    "inftrees",
    "trees",
    "uncompr",
    "zutil"
]

if __name__ == "__main__":
    success = 0
    failed = 0
    print(len(default_progs), " files to execute tests for.")
    for i, program_name in enumerate(default_progs, 1):
        print(f"\n{'='*70}")
        print(f"Executing tests for zlib files: {program_name}")
        print(f"[{i}/{len(default_progs)}] {program_name}")
        print('='*70)
        try:
            run_build_execute_mutate_for_one_zlib_program(program_name, enable_mutation_testing=True)
            success += 1
            print(f"✓ {program_name} DONE")
        except Exception as e:
            failed += 1
            print(f"✗ {program_name} FAILED: {e}")
            continue  # Keep going to next program
    print(f"\n{'='*70}")
    print(f"SUMMARY: {success} success, {failed} failed")
    print('='*70)