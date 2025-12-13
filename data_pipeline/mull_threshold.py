import csv

def count_functions_above_threshold(file_path, threshold):
    """
    Count how many functions have mull_score > threshold.
    mull_score is treated as numeric; 'N/A' is ignored.
    """
    count = 0
    total = 0

    with open(file_path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            total += 1
            score = row['mull_score']
            if score != 'N/A':
                try:
                    score_val = float(score)
                    if score_val > threshold:
                        count += 1
                except ValueError:
                    pass  # skip invalid numbers

    print(f"Total functions: {total}")
    print(f"Functions with mull_score > {threshold}: {count}")
    return count

# Example usage
if __name__ == "__main__":
    file_path = "test_results_mull.txt"
    threshold = 50  # change as needed
    count_functions_above_threshold(file_path, threshold)
