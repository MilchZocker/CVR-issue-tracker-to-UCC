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

class PublicGitHubToAstuto:
    def __init__(self, astuto_api_key, astuto_base_url):
        self.github_api_url = "https://api.github.com"
        self.astuto_headers = {
            'Authorization': f'Bearer {astuto_api_key}',
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }
        self.astuto_base_url = astuto_base_url.rstrip('/')

    def print_astuto_info(self):
        """Print all available Astuto information"""
        logger.info("Fetching Astuto information...")
        
        # Get boards
        try:
            response = requests.get(f"{self.astuto_base_url}/api/v1/boards", headers=self.astuto_headers)
            response.raise_for_status()
            boards = response.json()
            
            print("\n=== ASTUTO BOARDS ===")
            print(json.dumps(boards, indent=2))
            
            # Print formatted board information
            print("\nAvailable Boards:")
            print("-----------------")
            for board in boards:
                print(f"Board ID: {board.get('id')}")
                print(f"Name: {board.get('name')}")
                print(f"Description: {board.get('description')}")
                print(f"Slug: {board.get('slug')}")
                print("-----------------")
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching boards: {e}")
            
        # Get post statuses
        try:
            response = requests.get(f"{self.astuto_base_url}/api/v1/post_statuses", headers=self.astuto_headers)
            response.raise_for_status()
            statuses = response.json()
            
            print("\n=== POST STATUSES ===")
            print(json.dumps(statuses, indent=2))
            
            # Print formatted status information
            print("\nAvailable Post Statuses:")
            print("----------------------")
            for status in statuses:
                print(f"Status ID: {status.get('id')}")
                print(f"Name: {status.get('name')}")
                print(f"Color: {status.get('color')}")
                print("----------------------")
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching post statuses: {e}")

    def get_github_issues(self, owner, repo):
        """Fetch issues from public GitHub repository using REST API"""
        logger.info(f"Fetching issues from {owner}/{repo}")
        headers = {
            'Accept': 'application/vnd.github.v3+json',
            'User-Agent': 'GitHub-Issue-Migrator'
        }
        
        issues = []
        page = 1
        while True:
            url = f"{self.github_api_url}/repos/{owner}/{repo}/issues"
            params = {
                'state': 'all',
                'page': page,
                'per_page': 100
            }
            
            try:
                logger.debug(f"Fetching page {page} of issues...")
                response = requests.get(url, headers=headers, params=params)
                response.raise_for_status()
                
                page_issues = response.json()
                if not page_issues:
                    break
                    
                issues.extend(page_issues)
                logger.info(f"Retrieved {len(page_issues)} issues from page {page}")
                page += 1
                
                if 'X-RateLimit-Remaining' in response.headers:
                    remaining = int(response.headers['X-RateLimit-Remaining'])
                    logger.debug(f"GitHub API rate limit remaining: {remaining}")
                    if remaining < 10:
                        logger.warning("Rate limit running low, waiting 60 seconds...")
                        time.sleep(60)
                        
            except requests.exceptions.RequestException as e:
                logger.error(f"Error fetching GitHub issues: {e}")
                break
                
        logger.info(f"Total issues fetched: {len(issues)}")
        return issues

    def create_astuto_post(self, board_id, issue):
        """Create a post in Astuto from GitHub issue"""
        logger.debug(f"Creating Astuto post for issue #{issue['number']}")
        url = f"{self.astuto_base_url}/api/v1/posts"
        
        # Convert labels to string
        labels = ", ".join([label['name'] for label in issue.get('labels', [])])
        
        # Truncate title to 128 characters
        title = issue['title']
        if len(title) > 128:
            title = title[:125] + "..."
        
        # Format description
        description = (
            f"{issue.get('body', 'No description provided')}\n\n"
            f"---\n"
            f"Originally from GitHub Issue #{issue['number']}\n"
            f"Status: {issue['state']}\n"
            f"Labels: {labels}\n"
            f"Created at: {issue['created_at']}\n"
            f"Original URL: {issue['html_url']}"
        )

        # Create request payload
        payload = {
            "title": title,
            "description": description,
            "board_id": str(board_id)
        }

        try:
            response = requests.post(
                url,
                json=payload,
                headers=self.astuto_headers,
                verify=True
            )
            
            response.raise_for_status()
            created_post = response.json()
            logger.info(f"Successfully created Astuto post for issue #{issue['number']}")
            
            # Update post status if labels exist
            if created_post and 'id' in created_post:
                self.update_post_status(created_post['id'], issue)
                
            return created_post
        except requests.exceptions.RequestException as e:
            logger.error(f"Error creating Astuto post for issue #{issue['number']}: {e}")
            if hasattr(e.response, 'text'):
                logger.error(f"Response content: {e.response.text}")
            return None

    def update_post_status(self, post_id, issue):
        """Update post status based on GitHub issue labels"""
        # Map GitHub labels to Astuto status IDs
        label_to_status = {
            "bug": 5,
            "documentation": 6,
            "duplicate": 7,
            "enhancement": 8,
            "good first issue": 9,
            "help wanted": 10,
            "invalid": 11,
            "question": 12,
            "wontfix": 13
        }
        
        # Get status ID from labels
        status_id = None
        for label in issue.get('labels', []):
            label_name = label['name'].lower()
            if label_name in label_to_status:
                status_id = label_to_status[label_name]
                logger.info(f"Found matching status ID {status_id} for label {label_name}")
                break
        
        if status_id:
            url = f"{self.astuto_base_url}/api/v1/posts/{post_id}/update_status"
            payload = {
                "post_status_id": status_id
            }
            
            try:
                response = requests.put(
                    url,
                    json=payload,
                    headers=self.astuto_headers,
                    verify=True
                )
                
                response.raise_for_status()
                logger.info(f"Successfully updated post {post_id} status to {status_id}")
                return True
            except requests.exceptions.RequestException as e:
                logger.error(f"Error updating post status: {e}")
                if hasattr(e.response, 'text'):
                    logger.error(f"Response content: {e.response.text}")
                return False

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
            response = requests.get(
                f"{self.astuto_base_url}/api/v1/boards",
                headers=self.astuto_headers
            )
            response.raise_for_status()
            connection_status['astuto'] = True
            logger.info("Astuto API connection successful")
        except requests.exceptions.RequestException as e:
            logger.error(f"Astuto API connection failed: {e}")

        return connection_status

    def sync_new_issues(self, owner, repo, board_id):
        """Sync only new issues that haven't been processed before and update existing post statuses"""
        logger.info("Checking for new issues...")
        issues = self.get_github_issues(owner, repo)
        
        # Get all existing posts
        try:
            url = f"{self.astuto_base_url}/api/v1/posts"
            response = requests.get(url, headers=self.astuto_headers)
            response.raise_for_status()
            existing_posts = response.json()
            logger.info(f"Found {len(existing_posts)} existing posts")
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching existing posts: {e}")
            return
        
        new_issues = 0
        for issue in issues:
            issue_number = issue['number']
            issue_reference = f"GitHub Issue #{issue_number}"
            
            # Check if post exists and get its ID
            existing_post = None
            for post in existing_posts:
                if issue_reference in post.get('description', ''):
                    existing_post = post
                    break
            
            if existing_post:
                # Update status of existing post
                logger.debug(f"Updating status for existing post #{existing_post['id']}")
                self.update_post_status(existing_post['id'], issue)
            else:
                # Create new post
                logger.info(f"Creating new post for issue #{issue_number}: {issue['title']}")
                result = self.create_astuto_post(board_id, issue)
                if result:
                    new_issues += 1
                time.sleep(1)
        
        logger.info(f"Sync completed. {new_issues} new issues processed.")

def run_sync():
    """Run the synchronization process"""
    astuto_api_key = os.getenv('ASTUTO_API_KEY')
    astuto_base_url = os.getenv('ASTUTO_BASE_URL')
    board_id = os.getenv('ASTUTO_BOARD_ID')
    
    owner = "Alpha-Blend-Interactive"
    repo = "ChilloutVR"

    syncer = PublicGitHubToAstuto(astuto_api_key, astuto_base_url)
    
    # Print Astuto information before running sync
    syncer.print_astuto_info()
    
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
