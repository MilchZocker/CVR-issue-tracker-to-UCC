import requests
from datetime import datetime
import os
import time
import logging
import sys
import schedule

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
            'Content-Type': 'application/json'
        }
        self.astuto_base_url = astuto_base_url.rstrip('/')

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

    def check_post_exists(self, board_id, issue_number):
        """Check if a post already exists for this GitHub issue"""
        try:
            url = f"{self.astuto_base_url}/api/v1/boards/{board_id}/posts"
            response = requests.get(url, headers=self.astuto_headers)
            response.raise_for_status()
            posts = response.json()

            issue_reference = f"GitHub Issue #{issue_number}"
            for post in posts:
                if issue_reference in post.get('description', ''):
                    logger.info(f"Found existing post for GitHub issue #{issue_number}")
                    return True

            return False

        except requests.exceptions.RequestException as e:
            logger.error(f"Error checking existing posts: {e}")
            return False

    def create_astuto_post(self, board_id, issue):
        """Create a post in Astuto from GitHub issue"""
        logger.debug(f"Creating Astuto post for issue #{issue['number']}")
        url = f"{self.astuto_base_url}/api/v1/boards/{board_id}/posts"
        
        # Convert labels to string
        labels = ", ".join([label['name'] for label in issue.get('labels', [])])
        
        data = {
            'title': issue['title'],
            'description': f"""
                {issue.get('body', 'No description provided')}\n\n
                ---\n
                Originally from GitHub Issue #{issue['number']}\n
                Status: {issue['state']}\n
                Labels: {labels}\n
                Created at: {issue['created_at']}\n
                Original URL: {issue['html_url']}
            """,
            'board_id': board_id,
            'status': 'under_review' if issue['state'] == 'open' else 'closed'
        }

        try:
            response = requests.post(url, json=data, headers=self.astuto_headers)
            response.raise_for_status()
            logger.info(f"Successfully created Astuto post for issue #{issue['number']}")
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Error creating Astuto post for issue #{issue['number']}: {e}")
            return None

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
        """Sync only new issues that haven't been processed before"""
        logger.info("Checking for new issues...")
        issues = self.get_github_issues(owner, repo)
        
        new_issues = 0
        for issue in issues:
            issue_number = issue['number']
            
            if not self.check_post_exists(board_id, issue_number):
                logger.info(f"Creating new post for issue #{issue_number}: {issue['title']}")
                result = self.create_astuto_post(board_id, issue)
                if result:
                    new_issues += 1
                time.sleep(1)
            else:
                logger.debug(f"Skipping issue #{issue_number} - already exists in Astuto")
        
        logger.info(f"Sync completed. {new_issues} new issues processed.")

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
