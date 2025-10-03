import pandas as pd
import os
import json
import argparse
from ydata_profiling import ProfileReport
from dotenv import load_dotenv

# LangChain specific imports
from langchain_openai import ChatOpenAI
from langchain.globals import set_llm_cache
from langchain_community.cache import SQLiteCache
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate


# Ensure report directory exists
REPORT_DIR = "report"
os.makedirs(REPORT_DIR, exist_ok=True)


def analyze_job_listings(directory_path, output_path=None, base_name="report", file_limit=1000):
    """
    Analyzes job listings from JSON files in a given directory and generates a profiling report.

    Args:
        directory_path (str): The path to the directory containing JSON files with job listings.
        output_path (str, optional): The base path for the output report files (without extension).
                                     If not provided, uses base_name with '_raw' suffix.
        base_name (str, optional): The base name for output files. Defaults to "report".
        file_limit (int, optional): Maximum number of files to process. Defaults to 1000.
    """
    if output_path is None:
        output_path = os.path.join(REPORT_DIR, f"{base_name}_raw")
    
    print(f"Step 1: Analyzing job listings from '{directory_path}'...")
    
    all_data = []
    files_processed = 0
    
    for filename in os.listdir(directory_path):
        if filename.endswith(".json"):
            if files_processed >= file_limit:
                print(f"Reached file limit of {file_limit}. Stopping file processing.")
                break
                
            filepath = os.path.join(directory_path, filename)
            try:
                with open(filepath, 'r') as f:
                    data = json.load(f)
                    all_data.append(data)
                    files_processed += 1
            except json.JSONDecodeError as e:
                print(f"Error decoding JSON from {filepath}: {e}")
            except Exception as e:
                print(f"Error reading file {filepath}: {e}")

    if not all_data:
        print(f"No JSON files found or loaded from {directory_path}")
        return

    df = pd.json_normalize(all_data, sep=" > ")
    profile = ProfileReport(df, title="Profiling Report")

    profile.to_file(f"{output_path}.html")
    profile.to_file(f"{output_path}.json")
    
    print(f"-> Analysis complete! Reports saved to '{output_path}.html' and '{output_path}.json'")
    return f"{output_path}.json"


def clean_variable_stats_from_json(file_path: str, output_file_path: str = None, base_name: str = "report") -> dict:
    """
    Reads a JSON analysis report from a file path, extracts and cleans the 
    'variables' section.

    This function isolates the 'variables' dictionary and, for each variable,
    keeps only a predefined set of statistical keys.

    Args:
        file_path: The path to the input JSON file.
        output_file_path: The path to save the cleaned output.
        base_name: The base name for output files. Defaults to "report".

    Returns:
        A cleaned dictionary containing only the specified statistics for each 
        variable. Returns an empty dictionary if the file is not found, is not 
        valid JSON, or lacks a 'variables' key.
    """
    if output_file_path is None:
        output_file_path = os.path.join(REPORT_DIR, f"{base_name}_cleaned.json")
    
    print(f"Step 2: Cleaning variable stats from '{file_path}'...")
    
    # Define the specific keys you want to keep for each variable
    keys_to_keep = {
        "n_distinct",
        "p_distinct",
        "type",
        "value_counts_without_nan",
        "n_missing",
        "n",
        "p_missing",
        "min",
        "max",
        "mean",
        "std",
    }

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"Error: The file at {file_path} was not found.")
        return {}
    except json.JSONDecodeError:
        print(f"Error: The file at {file_path} is not a valid JSON file.")
        return {}

    # Get the original 'variables' dictionary, or an empty one if it doesn't exist
    original_variables = data.get('variables', {})
    
    # Use a dictionary comprehension to build the new, cleaned dictionary.
    # This iterates through each variable and its stats in the original dictionary.
    cleaned_data = {
        variable_name: {
            # For each variable, create a new inner dictionary.
            # Only include the key and its value if the key is in our 'keys_to_keep' set.
            key: stats_dict.get(key) 
            for key in keys_to_keep 
            if key in stats_dict
        }
        for variable_name, stats_dict in original_variables.items()
    }

    with open(output_file_path, 'w', encoding='utf-8') as f_out:
        json.dump(cleaned_data, f_out, indent=4)
    
    print(f"-> Cleaning complete! Saved to '{output_file_path}'")
    return cleaned_data


def shrink_json_profile(source_path: str, output_path: str = None, base_name: str = "report", max_keys: int = 10, max_chars_for_text: int = 1000):
    """
    Reads a JSON profile, shrinks the 'value_counts_without_nan' section
    based on new rules, and writes the result to a new JSON file.

    Shrinking Rules:
    - "Categorical" type: No changes are made.
    - "Text" type: Keeps keys up to a max of 10 keys OR a cumulative
      character length of 500 for the keys, whichever is met first.
    - All other types: Keeps a maximum of the first 10 keys.
    - If any keys are removed, a "more ...": -1 entry is added.

    Args:
        source_path (str): The path to the input JSON file.
        output_path (str, optional): The path for the output JSON file.
                                     If not provided, uses base_name with '_shrinked' suffix.
        base_name (str, optional): The base name for output files. Defaults to "report".
        max_keys (int, optional): The maximum number of keys to keep for non-Categorical types.
                                  Defaults to 10.
        max_chars_for_text (int, optional): For "Text" type, max total characters for all keys combined.
                                            Defaults to 1000.
    """
    if output_path is None:
        output_path = os.path.join(REPORT_DIR, f"{base_name}_shrinked.json")
    
    print(f"Step 3: Shrinking data from '{source_path}'...")
    
    try:
        with open(source_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"Error: The file '{source_path}' was not found.")
        return
    except json.JSONDecodeError:
        print(f"Error: The file '{source_path}' is not a valid JSON file.")
        return

    # Iterate over each column in the data
    for column_name, column_data in data.items():
        if "type" not in column_data or "value_counts_without_nan" not in column_data:
            continue

        col_type = column_data["type"]
        value_counts = column_data["value_counts_without_nan"]
        original_key_count = len(value_counts)
        new_value_counts = {}

        # Rule for "Categorical" type: skip all shrinking logic
        if col_type == "Categorical":
            continue

        # Rule for "Text" type: apply dual-limit logic
        elif col_type == "Text":
            char_count = 0
            for key, value in value_counts.items():
                # Stop if we hit the 10-key limit
                if len(new_value_counts) >= max_keys:
                    break
                
                # Stop if adding the next key exceeds the character limit
                # (but always include at least one key)
                if char_count + len(key) > max_chars_for_text and len(new_value_counts) > 0:
                    break
                
                new_value_counts[key] = value
                char_count += len(key)
        
        # Rule for all other types: apply the 10-key limit
        else:
            if len(value_counts) > max_keys:
                first_items = list(value_counts.items())[:max_keys]
                new_value_counts = dict(first_items)
            else:
                # If 10 or fewer keys, keep them all
                new_value_counts = value_counts

        # After processing, check if keys were removed and add "more ..."
        # This applies to all non-Categorical types that were processed.
        if len(new_value_counts) < original_key_count:
            new_value_counts["more ..."] = -1
        
        # Update the column data with the shrunk dictionary
        column_data["value_counts_without_nan"] = new_value_counts

    # Write the modified data to the output file
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
        
    print(f"-> Shrinking complete! Saved to '{output_path}'")


def enrich_dataset_metadata(input_path: str, output_path: str = None, base_name: str = "report"):
    """
    Loads a JSON data profile, generates an overall description, then generates
    a description for each column using an LLM via OpenRouter, and saves the
    enriched data. This version uses the official langchain-openai integration method.

    Args:
        input_path (str): The path to the input JSON data profile.
        output_path (str): The path to save the enriched JSON output.
                           If not provided, uses base_name with '_enriched' suffix.
        base_name (str, optional): The base name for output files. Defaults to "report".
    """
    if output_path is None:
        output_path = os.path.join(REPORT_DIR, f"{base_name}_enriched.json")
    
    # --- 1. SETUP AND INITIALIZATION ---
    print(f"Step 4: Enriching metadata from '{input_path}'...")

    # Load environment variables from .env file
    load_dotenv()
    api_key = os.getenv("OPENROUTER_API_KEY")
    base_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    site_url = os.getenv("YOUR_SITE_URL", "https://github.com/data-describer")
    site_name = os.getenv("YOUR_SITE_NAME", "Data Describer")

    if not all([api_key, base_url, site_url, site_name]):
        raise ValueError(
            "One or more required environment variables are missing. "
            "Please check your .env file for: OPENROUTER_API_KEY, "
            "OPENROUTER_BASE_URL, YOUR_SITE_URL, YOUR_SITE_NAME"
        )

    # Enable caching for LangChain to avoid re-running identical queries
    print("Setting up LLM cache (./.langchain.db)...")
    set_llm_cache(SQLiteCache(database_path=".langchain.db"))

    # --- UPDATED LLM INITIALIZATION using ChatOpenAI ---
    print("Initializing LLM via OpenRouter endpoint...")
    llm = ChatOpenAI(
        model="anthropic/claude-3.5-sonnet",
        temperature=0.1,
        api_key=api_key,
        base_url=base_url,
        default_headers={
            "HTTP-Referer": site_url,
            "X-Title": site_name,
        }
    )
    output_parser = StrOutputParser()

    # --- 2. LOAD AND PREPARE DATA ---
    print(f"Loading data from '{input_path}'...")
    try:
        with open(input_path, 'r', encoding='utf-8') as f:
            data_profile = json.load(f)
    except FileNotFoundError:
        print(f"Error: Input file not found at '{input_path}'")
        return
    except json.JSONDecodeError:
        print(f"Error: Could not decode JSON from '{input_path}'")
        return

    compressed_profile_str = json.dumps(data_profile, separators=(',', ':'))
    column_names = list(data_profile.keys())
    print(f"Found {len(column_names)} columns: {', '.join(column_names)}")

    # --- 3. GENERATE OVERALL DATASET DESCRIPTION ---
    print("\nGenerating overall dataset description (approx. 200 words)...")
    overall_prompt = ChatPromptTemplate.from_template(
        """
        You are an expert data analyst. Based on the following JSON data profile,
        which describes the columns of a dataset, provide a summary of what the
        entire dataset is likely about. The description should be about 200 words.

        Data Profile:
        {data_profile}
        """
    )
    overall_chain = overall_prompt | llm | output_parser
    overall_description = overall_chain.invoke({"data_profile": compressed_profile_str})
    print("-> Overall description generated successfully.")

    print("\n--- RAW LLM RESPONSE (Overall Description) ---")
    print(overall_description)
    print("---------------------------------------------\n")

    # --- 4. GENERATE DESCRIPTIONS FOR EACH COLUMN ---
    print("\nGenerating descriptions for each individual column...")
    enriched_columns = []
    
    column_prompt = ChatPromptTemplate.from_template(
        """
        You are an expert data analyst. You are analyzing a dataset.
        For context, here is a list of all columns in the dataset: {all_column_names}
        
        Your task is to describe the specific column named '{column_name}'.
        Use ONLY the JSON profiling data provided below to write a concise, one-paragraph
        description of what this specific column contains and its key characteristics.

        Profiling data for column '{column_name}':
        {column_data}
        """
    )
    column_chain = column_prompt | llm | output_parser

    for i, (col_name, col_data) in enumerate(data_profile.items()):
        print(f"  ({i+1}/{len(column_names)}) Processing column: '{col_name}'...")
        
        column_description = column_chain.invoke({
            "all_column_names": column_names,
            "column_name": col_name,
            "column_data": json.dumps(col_data)
        })

        print(f"    --- RAW LLM RESPONSE for '{col_name}' ---")
        print(f"    {column_description.strip()}")
        print("    ----------------------------------------")
        
        enriched_column_data = {
            "column_name": col_name,
            **col_data,
            "description": column_description.strip()
        }
        enriched_columns.append(enriched_column_data)

    print("-> All column descriptions generated successfully.")

    # --- 5. ASSEMBLE AND SAVE THE FINAL OUTPUT ---
    final_output = {
        "description": overall_description.strip(),
        "columns": enriched_columns
    }

    print(f"\nSaving enriched metadata to '{output_path}'...")
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(final_output, f, ensure_ascii=False, indent=4)

    print("\nProcess complete!")
    print(f"Enriched data saved at: {os.path.abspath(output_path)}")


def run_all_steps(directory_path, base_name="report", file_limit=1000):
    """
    Runs all steps in sequence: analyze, clean, shrink, enrich.
    
    Args:
        directory_path (str): The path to the directory containing JSON files with job listings.
        base_name (str, optional): The base name for output files. Defaults to "report".
        file_limit (int, optional): Maximum number of files to process. Defaults to 1000.
    """
    print("=" * 80)
    print("RUNNING ALL STEPS AUTOMATICALLY")
    print("=" * 80)
    
    # Step 1: Analyze
    raw_report_path = analyze_job_listings(directory_path, base_name=base_name, file_limit=file_limit)
    print("\n" + "=" * 80 + "\n")
    
    # Step 2: Clean
    clean_variable_stats_from_json(raw_report_path, base_name=base_name)
    print("\n" + "=" * 80 + "\n")
    
    # Step 3: Shrink
    shrink_json_profile(os.path.join(REPORT_DIR, f"{base_name}_cleaned.json"), base_name=base_name)
    print("\n" + "=" * 80 + "\n")
    
    # Step 4: Enrich
    enrich_dataset_metadata(os.path.join(REPORT_DIR, f"{base_name}_shrinked.json"), base_name=base_name)
    print("\n" + "=" * 80 + "\n")
    
    print("ALL STEPS COMPLETED SUCCESSFULLY!")
    print("=" * 80)


def main():
    parser = argparse.ArgumentParser(
        description="Explore and analyze job listing data with multiple processing steps."
    )
    parser.add_argument(
        "directory",
        type=str,
        help="Directory containing job listing JSON files"
    )
    parser.add_argument(
        "-a", "--all",
        action="store_true",
        help="Run all steps automatically (analyze, clean, shrink, enrich)"
    )
    parser.add_argument(
        "-c", "--clean",
        action="store_true",
        help="Run the cleaning step only"
    )
    parser.add_argument(
        "-s", "--shrink",
        action="store_true",
        help="Run the shrink step only"
    )
    parser.add_argument(
        "-e", "--enrich",
        action="store_true",
        help="Run the enrich step only"
    )
    parser.add_argument(
        "-n", "--name",
        type=str,
        default="report",
        help="Base name for output files (default: report)"
    )
    parser.add_argument(
        "-l", "--limit",
        type=int,
        default=1000,
        help="Maximum number of files to process (default: 1000)"
    )
    
    args = parser.parse_args()
    
    # Determine which step to run
    if args.all:
        run_all_steps(args.directory, base_name=args.name, file_limit=args.limit)
    elif args.clean:
        clean_variable_stats_from_json(
            os.path.join(REPORT_DIR, f"{args.name}_raw.json"),
            base_name=args.name
        )
    elif args.shrink:
        shrink_json_profile(
            os.path.join(REPORT_DIR, f"{args.name}_cleaned.json"),
            base_name=args.name
        )
    elif args.enrich:
        enrich_dataset_metadata(
            os.path.join(REPORT_DIR, f"{args.name}_shrinked.json"),
            base_name=args.name
        )
    else:
        # No flags: run first step (analyze)
        analyze_job_listings(args.directory, base_name=args.name, file_limit=args.limit)


if __name__ == "__main__":
    main()
