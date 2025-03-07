import requests
from datetime import datetime
import os
import time
import logging
import sys
import schedule
import json

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('github_to_astuto_sync.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

class RateLimiter:
    def __init__(self, requests_per_window=100, window_size=300):  # 100 requests per 5 minutes (300 seconds)
        self.requests_per_window = requests_per_window
        self.window_size = window_size
        self.requests = []
        
    def can_make_request(self):
        current_time = time.time()
        # Remove requests older than window_size
        self.requests = [req_time for req_time in self.requests 
                        if current_time - req_time < self.window_size]
        
        return len(self.requests) < self.requests_per_window
    
    def add_request(self):
        self.requests.append(time.time())
    
    def wait_time(self):
        if not self.requests:
            return 0
        
        current_time = time.time()
        oldest_request = min(self.requests)
        return max(0, self.window_size - (current_time - oldest_request))

class PublicGitHubToAstuto:
    def __init__(self, astuto_api_key, astuto_base_url):
        self.github_api_url = "https://api.github.com"
        self.astuto_headers = {
            'Authorization': f'Bearer {astuto_api_key}',
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }
        self.astuto_base_url = astuto_base_url.rstrip('/')
        self.astuto_boards = {}
        self.astuto_statuses = {}
        self.last_sync_file = "last_sync.json"
        self.rate_limiter = RateLimiter()
        self.max_retries = 3
        self.load_sync_state()
        self.initialize_astuto_mappings()

    def test_connections(self):
        """Test both GitHub and Astuto API connections"""
        connection_status = {
            'github': False,
            'astuto': False
        }

        # Test GitHub API
        try:
            logger.info("Testing GitHub API connection...")
            response = requests.get(
                f"{self.github_api_url}/rate_limit",
                headers={'User-Agent': 'GitHub-Issue-Migrator'}
            )
            response.raise_for_status()
            connection_status['github'] = True
            remaining_rate = response.json()['resources']['core']['remaining']
            logger.info(f"GitHub API connection successful. Rate limit remaining: {remaining_rate}")
        except requests.exceptions.RequestException as e:
            logger.error(f"GitHub API connection failed: {e}")

        # Test Astuto API
        try:
            logger.info("Testing Astuto API connection...")
            response = self.make_astuto_request('get', f"{self.astuto_base_url}/api/v1/boards", headers=self.astuto_headers)
            connection_status['astuto'] = True
            logger.info("Astuto API connection successful")
        except requests.exceptions.RequestException as e:
            logger.error(f"Astuto API connection failed: {e}")

        return connection_status

    def make_astuto_request(self, method, url, **kwargs):
        """Make a rate-limited request to Astuto API with retries"""
        for attempt in range(self.max_retries):
            if not self.rate_limiter.can_make_request():
                wait_time = self.rate_limiter.wait_time()
                logger.warning(f"Rate limit reached. Waiting {wait_time:.2f} seconds...")
                time.sleep(wait_time)

            try:
                self.rate_limiter.add_request()
                response = requests.request(method, url, **kwargs)
                
                if response.status_code == 429:  # Too Many Requests
                    wait_time = 2 ** attempt * 30  # Exponential backoff starting at 30 seconds
                    logger.warning(f"Rate limit exceeded. Waiting {wait_time} seconds before retry...")
                    time.sleep(wait_time)
                    continue
                
                response.raise_for_status()
                return response
                
            except requests.exceptions.RequestException as e:
                if attempt == self.max_retries - 1:
                    raise
                wait_time = 2 ** attempt * 30
                logger.warning(f"Request failed. Waiting {wait_time} seconds before retry...")
                time.sleep(wait_time)
        
        raise Exception("Max retries exceeded")

    def load_sync_state(self):
        """Load the last sync state from file"""
        try:
            with open(self.last_sync_file, 'r') as f:
                self.sync_state = json.load(f)
        except FileNotFoundError:
            self.sync_state = {
                'last_sync': None,
                'processed_issues': {}
            }

    def save_sync_state(self):
        """Save the current sync state to file"""
        with open(self.last_sync_file, 'w') as f:
            json.dump(self.sync_state, f)

    def initialize_astuto_mappings(self):
        """Initialize mappings for Astuto boards and statuses"""
        try:
            response = self.make_astuto_request('get', f"{self.astuto_base_url}/api/v1/boards", headers=self.astuto_headers)
            boards = response.json()
            self.astuto_boards = {board['name'].lower(): str(board['id']) for board in boards}
            logger.info(f"Loaded {len(self.astuto_boards)} Astuto boards")
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching Astuto boards: {e}")

        try:
            response = self.make_astuto_request('get', f"{self.astuto_base_url}/api/v1/post_statuses", headers=self.astuto_headers)
            statuses = response.json()
            self.astuto_statuses = {status['name'].lower(): status['id'] for status in statuses}
            logger.info(f"Loaded {len(self.astuto_statuses)} Astuto statuses")
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching Astuto statuses: {e}")

def determine_board(self, issue_labels):
    """Determine which board to use based on issue labels"""
    assignment_reason = "default"
    assigned_board = "2"  # Default to Bug Reports

    # First check for hellonext source - highest priority
    for label in issue_labels:
        label_name = label['name'].lower()
        if label_name == "source: hellonext":
            assigned_board = "4"  # Hellonext board
            assignment_reason = "hellonext source"
            logger.info(f"Board assignment: {assigned_board} (Reason: {assignment_reason})")
            return assigned_board

    # If not hellonext source, follow normal priority order
    for label in issue_labels:
        label_name = label['name'].lower()
        
        # Priority 2: Direct board name matches
        if label_name in self.astuto_boards:
            assigned_board = self.astuto_boards[label_name]
            assignment_reason = f"matched board name: {label_name}"
            break
        # Priority 3: Special label mappings
        elif label_name == "type: bug":
            assigned_board = "2"
            assignment_reason = "bug type label"
            break
        elif label_name in ["type: feature-request", "type: enhancement"]:
            assigned_board = "1"
            assignment_reason = "feature/enhancement type label"
            break

    logger.info(f"Board assignment: {assigned_board} (Reason: {assignment_reason})")
    return assigned_board


    def get_github_issues(self, owner, repo):
        """Fetch issues from GitHub with date filtering and retry logic"""
        logger.info(f"Fetching issues from {owner}/{repo}")
        headers = {
            'Accept': 'application/vnd.github.v3+json',
            'User-Agent': 'GitHub-Issue-Migrator'
        }
        
        issues = []
        page = 1
        
        while True:
            params = {
                'state': 'all',
                'page': page,
                'per_page': 50,
                'sort': 'updated',
                'direction': 'desc'
            }
            
            if self.sync_state['last_sync']:
                params['since'] = self.sync_state['last_sync']
            
            for attempt in range(3):
                try:
                    response = requests.get(
                        f"{self.github_api_url}/repos/{owner}/{repo}/issues",
                        headers=headers,
                        params=params,
                        timeout=30
                    )
                    response.raise_for_status()
                    break
                except requests.exceptions.RequestException as e:
                    if attempt == 2:
                        logger.error(f"Failed to fetch page {page} after 3 attempts")
                        raise
                    wait_time = 2 ** attempt
                    logger.warning(f"Attempt {attempt + 1} failed, waiting {wait_time} seconds...")
                    time.sleep(wait_time)
            
            page_issues = response.json()
            if not page_issues:
                break
            
            issues.extend(page_issues)
            logger.info(f"Retrieved {len(page_issues)} issues from page {page}")
            
            if 'X-RateLimit-Remaining' in response.headers:
                remaining = int(response.headers['X-RateLimit-Remaining'])
                if remaining < 10:
                    logger.warning("Rate limit running low, waiting 60 seconds...")
                    time.sleep(60)
            
            page += 1
            
        return issues

    def get_all_posts(self):
        """Fetch all posts from Astuto"""
        try:
            response = self.make_astuto_request('get', f"{self.astuto_base_url}/api/v1/posts", headers=self.astuto_headers)
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching existing posts: {e}")
            return []

    def map_issues_to_posts(self, existing_posts):
        """Create mapping of GitHub issue numbers to Astuto posts"""
        issue_to_post = {}
        for post in existing_posts:
            desc = post.get('description', '')
            if 'GitHub Issue #' in desc:
                try:
                    issue_num = int(desc.split('GitHub Issue #')[1].split('\n')[0])
                    issue_to_post[issue_num] = post
                except (ValueError, IndexError):
                    continue
        return issue_to_post

    def create_astuto_post(self, board_id, issue):
        """Create a post in Astuto from GitHub issue with rate limiting"""
        logger.debug(f"Creating Astuto post for issue #{issue['number']}")
        url = f"{self.astuto_base_url}/api/v1/posts"
        
        labels = ", ".join([label['name'] for label in issue.get('labels', [])])
        title = issue['title'][:125] + "..." if len(issue['title']) > 128 else issue['title']
        
        description = (
            f"{issue.get('body', 'No description provided')}\n\n"
            f"---\n"
            f"Originally from GitHub Issue #{issue['number']}\n"
            f"Status: {issue['state']}\n"
            f"Labels: {labels}\n"
            f"Created at: {issue['created_at']}\n"
            f"Original URL: [{issue['html_url']}]({issue['html_url']})"
        )

        payload = {
            "title": title,
            "description": description,
            "board_id": str(board_id),
            "created_at": issue['created_at'],
            "updated_at": issue['updated_at']
        }

        try:
            response = self.make_astuto_request(
                'post',
                url,
                json=payload,
                headers=self.astuto_headers,
                verify=True
            )
            
            created_post = response.json()
            logger.info(f"Successfully created Astuto post for issue #{issue['number']}")
            
            if created_post and 'id' in created_post:
                self.update_post_status(created_post['id'], issue)
                
            return created_post
        except Exception as e:
            logger.error(f"Error creating Astuto post for issue #{issue['number']}: {e}")
            if hasattr(e, 'response') and hasattr(e.response, 'text'):
                logger.error(f"Response content: {e.response.text}")
            return None

    def update_existing_post(self, issue, existing_post):
        """Update existing post with rate limiting"""
        post_id = existing_post['id']
        url = f"{self.astuto_base_url}/api/v1/posts/{post_id}"
        
        new_title = issue['title'][:128] if len(issue['title']) > 128 else issue['title']
        new_description = self.format_issue_description(issue)
        
        payload = {
            "title": new_title,
            "description": new_description,
            "updated_at": issue['updated_at']
        }
        
        try:
            self.make_astuto_request('put', url, json=payload, headers=self.astuto_headers)
            logger.info(f"Updated content for post {post_id}")
            return True
        except Exception as e:
            logger.error(f"Error updating post content: {e}")
            return False

    def needs_update(self, issue, existing_post):
        """Check if an issue needs to be updated in Astuto"""
        issue_number = str(issue['number'])
        issue_updated = issue['updated_at']
        
        if issue_number in self.sync_state['processed_issues']:
            last_processed = self.sync_state['processed_issues'][issue_number]
            if last_processed >= issue_updated:
                return False
        
        current_title = existing_post.get('title', '')
        current_description = existing_post.get('description', '')
        
        new_title = issue['title'][:128] if len(issue['title']) > 128 else issue['title']
        new_description = self.format_issue_description(issue)
        
        labels_changed = self.have_labels_changed(issue, existing_post)
        
        return (current_title != new_title or 
                current_description != new_description or 
                labels_changed)

    def have_labels_changed(self, issue, existing_post):
        """Check if issue labels have changed"""
        current_labels = set(label['name'] for label in issue.get('labels', []))
        desc = existing_post.get('description', '')
        labels_line = next((line for line in desc.split('\n') if line.startswith('Labels:')), '')
        existing_labels = set(label.strip() for label in labels_line.replace('Labels:', '').split(',') if label.strip())
        return current_labels != existing_labels

    def format_issue_description(self, issue):
        """Format the description for an Astuto post"""
        labels = ", ".join([label['name'] for label in issue.get('labels', [])])
        return (
            f"{issue.get('body', 'No description provided')}\n\n"
            f"---\n"
            f"Originally from GitHub Issue #{issue['number']}\n"
            f"Status: {issue['state']}\n"
            f"Labels: {labels}\n"
            f"Created at: {issue['created_at']}\n"
            f"Original URL: [{issue['html_url']}]({issue['html_url']})"
        )

    def update_post_status(self, post_id, issue):
        """Update post status based on GitHub issue labels with rate limiting"""
        matched_statuses = []
        
        for label in issue.get('labels', []):
            label_name = label['name'].lower()
            if label_name in self.astuto_statuses:
                matched_statuses.append((label_name, self.astuto_statuses[label_name]))
                logger.info(f"Matched label {label_name} to status ID {self.astuto_statuses[label_name]}")
        
        if not matched_statuses and str(issue.get('board_id')) == "2":
            if "type: bug" in self.astuto_statuses:
                matched_statuses.append(("type: bug", self.astuto_statuses["type: bug"]))
        
        if matched_statuses:
            highest_status = max(matched_statuses, key=lambda x: x[1])
            url = f"{self.astuto_base_url}/api/v1/posts/{post_id}/update_status"
            payload = {"post_status_id": highest_status[1]}
            
            try:
                self.make_astuto_request('put', url, json=payload, headers=self.astuto_headers)
                logger.info(f"Successfully updated post {post_id} status to {highest_status[1]} (from label {highest_status[0]})")
                return True
            except Exception as e:
                logger.error(f"Error updating post status: {e}")
                if hasattr(e, 'response') and hasattr(e.response, 'text'):
                    logger.error(f"Response content: {e.response.text}")
                return False

    def sync_new_issues(self, owner, repo, board_id):
        """Sync new issues and update existing ones"""
        logger.info("Starting sync process...")
        issues = self.get_github_issues(owner, repo)
        
        try:
            existing_posts = self.get_all_posts()
            issue_to_post = self.map_issues_to_posts(existing_posts)
            
            new_issues = 0
            updated_issues = 0
            
            for issue in issues:
                # Add delay between operations to prevent rate limiting
                time.sleep(1)
                
                issue_number = issue['number']
                existing_post = issue_to_post.get(issue_number)
                
                if existing_post:
                    if self.needs_update(issue, existing_post):
                        if self.update_existing_post(issue, existing_post):
                            updated_issues += 1
                else:
                    assigned_board = self.determine_board(issue.get('labels', []))
                    if self.create_astuto_post(assigned_board, issue):
                        new_issues += 1
                
                self.sync_state['processed_issues'][str(issue_number)] = issue['updated_at']
                
            self.sync_state['last_sync'] = datetime.utcnow().isoformat()
            self.save_sync_state()
            
            logger.info(f"Sync completed. {new_issues} new issues, {updated_issues} updates")
            
        except Exception as e:
            logger.error(f"Error during sync: {e}")
            raise

def run_sync():
    """Run the synchronization process"""
    astuto_api_key = os.getenv('ASTUTO_API_KEY')
    astuto_base_url = os.getenv('ASTUTO_BASE_URL')
    board_id = os.getenv('ASTUTO_BOARD_ID')
    
    owner = "Alpha-Blend-Interactive"
    repo = "ChilloutVR"

    syncer = PublicGitHubToAstuto(astuto_api_key, astuto_base_url)
    
    connections = syncer.test_connections()
    if not all(connections.values()):
        logger.error("Connection tests failed. Skipping sync.")
        return

    syncer.sync_new_issues(owner, repo, board_id)

def main():
    required_vars = ['ASTUTO_API_KEY', 'ASTUTO_BASE_URL', 'ASTUTO_BOARD_ID']
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    if missing_vars:
        logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
        sys.exit(1)

    schedule.every(1).hour.do(run_sync)
    
    run_sync()
    
    logger.info("Script is running. Will check for new issues every hour.")
    try:
        while True:
            schedule.run_pending()
            time.sleep(60)
    except KeyboardInterrupt:
        logger.info("Script stopped by user")
        sys.exit(0)

if __name__ == "__main__":
    main()
