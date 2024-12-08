import requests
import re
from datetime import datetime
import json
import os
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, urlunparse

class ProteinAnalyzer:
    def __init__(self):
        self.relevant_sources = []
        self.non_relevant_sources = []
        self.sources_file = 'memlog/relevant_sources.json'
        self.non_relevant_file = 'memlog/non_relevant_sources.json'
        self.processed_urls = set()  # Track processed URLs to avoid duplicates
        self.load_existing_sources()

    def load_existing_sources(self):
        """Load existing sources if any."""
        if os.path.exists(self.sources_file):
            with open(self.sources_file, 'r') as f:
                self.relevant_sources = json.load(f)
                # Rebuild processed URLs set
                self.processed_urls = {
                    source.get('source_url', '') 
                    for source in self.relevant_sources 
                    if 'source_url' in source
                }
        
        if os.path.exists(self.non_relevant_file):
            with open(self.non_relevant_file, 'r') as f:
                self.non_relevant_sources = json.load(f)

    def save_sources(self):
        """Save both relevant and non-relevant sources."""
        with open(self.sources_file, 'w') as f:
            json.dump(self.relevant_sources, f, indent=4)
        print(f"\nSaved {len(self.relevant_sources)} relevant sources to {self.sources_file}")
        
        with open(self.non_relevant_file, 'w') as f:
            json.dump(self.non_relevant_sources, f, indent=4)
        print(f"Saved {len(self.non_relevant_sources)} non-relevant sources to {self.non_relevant_file}")

    def split_into_paragraphs(self, content):
        """Split content into paragraphs based on double newlines."""
        if isinstance(content, list):
            text = ''.join(content)
        else:
            text = content
        paragraphs = [p.strip() for p in re.split(r'\n\s*\n', text) if p.strip()]
        return paragraphs

    def normalize_url(self, url):
        """Normalize URLs to their proper format."""
        # Ensure URL has proper scheme
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url

        parsed = urlparse(url)
        path = parsed.path.rstrip('/')
        
        # Handle PubMed URLs
        pubmed_match = re.search(r'/?(\d+)/?$', path)
        if 'pubmed.ncbi.nlm.nih.gov' in parsed.netloc or (pubmed_match and 'ncbi.nlm.nih.gov' in parsed.netloc):
            return f'https://pubmed.ncbi.nlm.nih.gov/{pubmed_match.group(1)}/'
        
        # Handle PMC URLs
        pmc_match = re.search(r'PMC(\d+)', url)
        if pmc_match:
            return f'https://www.ncbi.nlm.nih.gov/pmc/articles/PMC{pmc_match.group(1)}/'
        
        # Handle DOI URLs
        if 'doi.org' in parsed.netloc:
            return urlunparse(parsed)
        
        return url

    def extract_urls(self, content):
        """Extract URLs from content, but only from Source: lines."""
        urls = set()
        text = content if isinstance(content, str) else ''.join(content)
        
        # Split content into sections by ================ separator
        sections = text.split('=' * 80)
        
        for section in sections:
            # Look for Source: line
            source_match = re.search(r'Source:\s*(https?://[^\s\n]+)', section)
            if source_match:
                url = source_match.group(1)
                normalized_url = self.normalize_url(url)
                urls.add(normalized_url)
        
        return list(urls)

    def fetch_url_content(self, url):
        """Fetch content from a URL."""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            
            normalized_url = self.normalize_url(url)
            print(f"\nFetching content from normalized URL: {normalized_url}")
            
            response = requests.get(normalized_url, headers=headers, timeout=10)
            response.raise_for_status()
            
            # Parse HTML content
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Special handling for PMC articles
            if 'ncbi.nlm.nih.gov/pmc' in normalized_url:
                article_content = soup.find('div', {'class': ['jig-ncbiinpagenav', 'article-details']})
                if article_content:
                    soup = article_content
            elif 'pubmed.ncbi.nlm.nih.gov' in normalized_url:
                article_content = soup.find('div', {'class': ['abstract-content', 'article-details']})
                if article_content:
                    soup = article_content
            
            # Remove script and style elements
            for script in soup(["script", "style"]):
                script.decompose()
            
            # Get text content
            text = soup.get_text()
            
            # Clean up whitespace
            lines = (line.strip() for line in text.splitlines())
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            text = ' '.join(chunk for chunk in chunks if chunk)
            
            print(f"Successfully fetched content ({len(text)} characters)")
            return text
        except Exception as e:
            print(f"Error fetching URL {url}: {str(e)}")
            # If PMC fails, try PubMed
            if 'pmc/articles/PMC' in url:
                try:
                    # Extract PMC ID and try PubMed
                    pmc_match = re.search(r'PMC(\d+)', url)
                    if pmc_match:
                        pubmed_url = f'https://pubmed.ncbi.nlm.nih.gov/{pmc_match.group(1)}/'
                        print(f"Trying PubMed URL instead: {pubmed_url}")
                        return self.fetch_url_content(pubmed_url)
                except Exception as e2:
                    print(f"Error fetching PubMed URL: {str(e2)}")
            return None

    def query_ollama(self, paragraph):
        """Query ollama phi model to check if paragraph contains relevant protein targets."""
        try:
            prompt = f"""Question: Does the following paragraph contain information about protein targets relevant to fibrolamellar carcinoma? Consider any proteins, enzymes, kinases, or molecular targets mentioned in relation to FLC. Answer only Yes or No.

Paragraph: {paragraph}

Answer:"""
            
            print(f"\nQuerying ollama for paragraph: {paragraph[:100]}...")
            
            response = requests.post('http://localhost:11434/api/generate', 
                json={
                    "model": "phi:latest",
                    "prompt": prompt
                },
                stream=False
            )
            
            if response.status_code == 200:
                result = response.json()
                answer = result.get('response', '').strip().lower()
                print(f"Ollama response: {answer}")
                return answer.startswith('yes')
            return False
        except Exception as e:
            print(f"Error querying ollama: {e}")
            return False

    def process_urls(self, urls, source_filename):
        """Process content from a list of URLs."""
        for url in urls:
            if url in self.processed_urls:
                print(f"Skipping already processed URL: {url}")
                continue
                
            print(f"\nProcessing URL: {url}")
            content = self.fetch_url_content(url)
            
            if content:
                print(f"Analyzing content from URL: {url}")
                paragraphs = self.split_into_paragraphs(content)
                print(f"Found {len(paragraphs)} paragraphs to analyze")
                
                relevant_paragraphs = []
                non_relevant_paragraphs = []
                
                for i, paragraph in enumerate(paragraphs, 1):
                    print(f"\nAnalyzing paragraph {i}/{len(paragraphs)}")
                    if self.query_ollama(paragraph):
                        relevant_paragraphs.append(paragraph)
                        print(f"Found relevant protein target in paragraph {i}")
                    else:
                        non_relevant_paragraphs.append(paragraph)
                        print(f"No relevant protein target in paragraph {i}")
                
                timestamp = datetime.now().isoformat()
                
                if relevant_paragraphs:
                    source_entry = {
                        'filename': source_filename,
                        'source_url': url,
                        'paragraphs': relevant_paragraphs,
                        'timestamp': timestamp
                    }
                    
                    # Check if this URL is already stored
                    if not any(s.get('source_url') == url for s in self.relevant_sources):
                        self.relevant_sources.append(source_entry)
                        print(f"\nAdded new source with {len(relevant_paragraphs)} relevant paragraphs from URL: {url}")
                
                if non_relevant_paragraphs:
                    non_relevant_entry = {
                        'filename': source_filename,
                        'source_url': url,
                        'paragraphs': non_relevant_paragraphs,
                        'timestamp': timestamp
                    }
                    
                    # Check if this URL is already stored
                    if not any(s.get('source_url') == url for s in self.non_relevant_sources):
                        self.non_relevant_sources.append(non_relevant_entry)
                        print(f"\nAdded new source with {len(non_relevant_paragraphs)} non-relevant paragraphs from URL: {url}")
                
                if relevant_paragraphs or non_relevant_paragraphs:
                    self.save_sources()
                
                self.processed_urls.add(url)

    def analyze_content(self, filename, content):
        """Analyze content and its referenced URLs for relevant protein targets."""
        print(f"\nAnalyzing content from file: {filename}")
        
        # First, analyze the content itself
        paragraphs = self.split_into_paragraphs(content)
        print(f"Found {len(paragraphs)} paragraphs to analyze in content")
        
        relevant_paragraphs = []
        non_relevant_paragraphs = []
        
        for i, paragraph in enumerate(paragraphs, 1):
            print(f"\nAnalyzing paragraph {i}/{len(paragraphs)}")
            if self.query_ollama(paragraph):
                relevant_paragraphs.append(paragraph)
                print(f"Found relevant protein target in paragraph {i}")
            else:
                non_relevant_paragraphs.append(paragraph)
                print(f"No relevant protein target in paragraph {i}")
        
        timestamp = datetime.now().isoformat()
        
        if relevant_paragraphs:
            source_entry = {
                'filename': filename,
                'paragraphs': relevant_paragraphs,
                'timestamp': timestamp
            }
            
            # Check if this exact content is already stored
            if not any(
                s.get('filename') == filename and 
                set(s.get('paragraphs', [])) == set(relevant_paragraphs) 
                for s in self.relevant_sources
            ):
                self.relevant_sources.append(source_entry)
                print(f"\nAdded new source with {len(relevant_paragraphs)} relevant paragraphs from file: {filename}")
        
        if non_relevant_paragraphs:
            non_relevant_entry = {
                'filename': filename,
                'paragraphs': non_relevant_paragraphs,
                'timestamp': timestamp
            }
            
            # Check if this exact content is already stored
            if not any(
                s.get('filename') == filename and 
                set(s.get('paragraphs', [])) == set(non_relevant_paragraphs) 
                for s in self.non_relevant_sources
            ):
                self.non_relevant_sources.append(non_relevant_entry)
                print(f"\nAdded new source with {len(non_relevant_paragraphs)} non-relevant paragraphs from file: {filename}")
        
        if relevant_paragraphs or non_relevant_paragraphs:
            self.save_sources()
        
        # Extract and process URLs from the content
        urls = self.extract_urls(content)
        if urls:
            print(f"\nFound {len(urls)} URLs in {filename}")
            self.process_urls(urls, filename)
        
        return bool(relevant_paragraphs) or bool(urls)
