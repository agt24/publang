""" Wrappers around OpenAI to make help embedding chunked documents """

import tqdm
import numpy as np
from publang.utils.split import split_pmc_document
from typing import Dict, List, Tuple
import concurrent.futures
from sklearn.metrics.pairwise import euclidean_distances
from publang.utils.oai import get_openai_embedding


def embed_pmc_articles(
    articles: List[Dict],
    model: str = "text-embedding-ada-002",
    min_chars: int = 30,
    max_chars: int = 4000,
    num_workers: int = 1,
    client=None,
) -> List[Dict[str, any]]:
    """Embeds PMC articles using OpenAI text embedding model.

    Args:
        articles (List[Dict]): A list of PMC articles to be embedded.
            Each article is a dictionary with keys 'pmcid' and 'text'.
        model (str, optional): The name of the text embedding model to be used
        min_chars (int, optional): The minimum number of characters in a chunk.
        max_chars (int, optional): The maximum number of characters in a chunk.
        num_workers (int, optional): The number of workers for parallelization.

    Returns:
        List[Dict[str, any]]: A list of dicts containing the embedded articles.

    """
    def _split_embed(article, model, min_chars, max_chars):
        split_doc = split_pmc_document(
            article['text'], min_chars=min_chars, max_chars=max_chars
        )

        if split_doc:
            # Embed each chunk
            for chunk in split_doc:
                res = get_openai_embedding(
                    chunk["content"], model, client=client,
                )
                chunk["embedding"] = res
                chunk["pmcid"] = article["pmcid"]
            return split_doc
        else:
            return []

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as exc:
        futures = [
            exc.submit(_split_embed, article, model, min_chars, max_chars)
            for article in articles
        ]

        results = []
        for future in tqdm.tqdm(futures, total=len(articles)):
            results += future.result()

    return results


def _rank_numbers(numbers: List[float]) -> List[Tuple[float, int]]:
    """Rank a list of numbers in descending order relative to their original index.

    Args:
        numbers (List[float]): The list of numbers to rank.

    Returns:
        List[Tuple[float, int]]: A list of tuples containing the number and its rank relative to its original index.
    """
    ranked_numbers = sorted([(num, i) for i, num in enumerate(numbers)])
    ranks = [0] * len(numbers)
    for rank, (num, index) in enumerate(ranked_numbers):
        ranks[index] = rank
    return ranks


def query_embeddings(
    embeddings: List[List], query_embedding: str, compute_ranks=True
) -> Tuple[List[float], List[int]]:
    """Query a list of embeddings with a search embeddding. Returns the distances and ranks of the embeddings."""

    embeddings = np.array(embeddings)

    distances = euclidean_distances(
        embeddings, np.array(query_embedding).reshape(1, -1), squared=True
    )

    return distances, _rank_numbers(distances)


def get_chunk_query_distance(
    embeddings_df, query, client=None, model="text-embedding-ada-002"
):
    # For every document, get distance and rank between query and embeddings
    query_embedding = get_openai_embedding(query, model, client=client)
    distances, ranks = zip(
        *[
            query_embeddings(sub_df["embedding"].tolist(), query_embedding)
            for _, sub_df in embeddings_df.groupby("pmcid", sort=False)
        ]
    )

    # Combine with meta-data into a df
    ranks_df = embeddings_df[["pmcid", "content", "start_char", "end_char"]].copy()
    ranks_df["distance"] = np.concatenate(distances)
    ranks_df["rank"] = np.concatenate(ranks)

    ranks_df.sort_values("distance", inplace=True)

    return ranks_df
