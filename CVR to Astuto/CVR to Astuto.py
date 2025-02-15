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
        self.astuto_boards = {}
        self.astuto_statuses = {}
        self.initialize_astuto_mappings()

    def initialize_astuto_mappings(self):
        """Initialize mappings for Astuto boards and statuses"""
        # Get boards
        try:
            response = requests.get(f"{self.astuto_base_url}/api/v1/boards", headers=self.astuto_headers)
            response.raise_for_status()
            boards = response.json()
            # Create mapping of board names to IDs (lowercase for case-insensitive matching)
            self.astuto_boards = {board['name'].lower(): str(board['id']) for board in boards}
            logger.info(f"Loaded {len(self.astuto_boards)} Astuto boards")
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching Astuto boards: {e}")

        # Get statuses
        try:
            response = requests.get(f"{self.astuto_base_url}/api/v1/post_statuses", headers=self.astuto_headers)
            response.raise_for_status()
            statuses = response.json()
            # Create mapping of status names to IDs (lowercase for case-insensitive matching)
            self.astuto_statuses = {status['name'].lower(): status['id'] for status in statuses}
            logger.info(f"Loaded {len(self.astuto_statuses)} Astuto statuses")
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching Astuto statuses: {e}")

    def determine_board(self, issue_labels):
        """Determine which board to use based on issue labels"""
        # Store the reason for board assignment for logging
        assignment_reason = "default"
        assigned_board = "2"  # Default to Bug Reports

        for label in issue_labels:
            label_name = label['name'].lower()
            
            # Priority 1: Hellonext source
            if label_name == "source: hellonext":
                assigned_board = "4"
                assignment_reason = "hellonext source"
                break
                
            # Priority 2: Direct board name matches
            if label_name in self.astuto_boards:
                assigned_board = self.astuto_boards[label_name]
                assignment_reason = f"matched board name: {label_name}"
                break
                
            # Priority 3: Special label mappings
            if label_name == "type: bug":
                assigned_board = "2"
                assignment_reason = "bug type label"
                break
            elif label_name in ["type: feature-request", "type: enhancement"]:
                assigned_board = "1"
                assignment_reason = "feature/enhancement type label"
                break

        logger.info(f"Board assignment: {assigned_board} (Reason: {assignment_reason})")
        return assigned_board

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
        
        # Format description with markdown link
        description = (
            f"{issue.get('body', 'No description provided')}\n\n"
            f"---\n"
            f"Originally from GitHub Issue #{issue['number']}\n"
            f"Status: {issue['state']}\n"
            f"Labels: {labels}\n"
            f"Created at: {issue['created_at']}\n"
            f"Original URL: [{issue['html_url']}]({issue['html_url']})"
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
        matched_statuses = []
        
        # Match GitHub labels to Astuto statuses
        for label in issue.get('labels', []):
            label_name = label['name'].lower()
            if label_name in self.astuto_statuses:
                matched_statuses.append((label_name, self.astuto_statuses[label_name]))
                logger.info(f"Matched label {label_name} to status ID {self.astuto_statuses[label_name]}")
        
        # If no status matches found and it's in bug board, set bug status
        if not matched_statuses and str(issue.get('board_id')) == "2":
            if "type: bug" in self.astuto_statuses:
                matched_statuses.append(("type: bug", self.astuto_statuses["type: bug"]))
        
        # Apply the highest status ID found
        if matched_statuses:
            highest_status = max(matched_statuses, key=lambda x: x[1])
            url = f"{self.astuto_base_url}/api/v1/posts/{post_id}/update_status"
            payload = {"post_status_id": highest_status[1]}
            
            try:
                response = requests.put(url, json=payload, headers=self.astuto_headers)
                response.raise_for_status()
                logger.info(f"Successfully updated post {post_id} status to {highest_status[1]} (from label {highest_status[0]})")
                return True
            except requests.exceptions.RequestException as e:
                logger.error(f"Error updating post status: {e}")
                if hasattr(e.response, 'text'):
                    logger.error(f"Response content: {e.response.text}")
                return False

    def sync_comments(self, post_id, issue_number, owner, repo):
        """Sync comments from GitHub issue to Astuto post"""
        try:
            # Fetch GitHub comments
            url = f"{self.github_api_url}/repos/{owner}/{repo}/issues/{issue_number}/comments"
            headers = {'Accept': 'application/vnd.github.v3+json', 'User-Agent': 'GitHub-Issue-Migrator'}
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            github_comments = response.json()
            
            # Get all existing comments
            create_url = f"{self.astuto_base_url}/api/v1/comments"
            try:
                response = requests.get(create_url, headers=self.astuto_headers)
                response.raise_for_status()
                existing_comments = response.json()
            except requests.exceptions.RequestException as e:
                logger.error(f"Error fetching existing comments: {e}")
                return
            
            # Create or update comments
            for github_comment in github_comments:
                comment_id = str(github_comment['id'])
                
                # Format new comment body
                new_comment_body = (
                    f"{github_comment['body']}\n\n"
                    f"---\n"
                    f"Originally commented by: [{github_comment['user']['login']}]({github_comment['user']['html_url']})\n"
                    f"Created at: {github_comment['created_at']}\n"
                    f"GitHub Comment URL: [{github_comment['html_url']}]({github_comment['html_url']})\n"
                    f"GitHub Comment ID: {comment_id}"
                )
                
                # Check if comment exists
                existing_comment = None
                for comment in existing_comments:
                    if f"GitHub Comment ID: {comment_id}" in comment.get('body', ''):
                        existing_comment = comment
                        break
                
                # Create payload
                payload = {
                    "body": new_comment_body,
                    "post_id": int(post_id),
                    "is_post_update": True
                }
                
                try:
                    if existing_comment:
                        # Update if content changed
                        if existing_comment['body'] != new_comment_body:
                            update_url = f"{self.astuto_base_url}/api/v1/comments/{existing_comment['id']}"
                            response = requests.put(update_url, json=payload, headers=self.astuto_headers)
                            response.raise_for_status()
                            logger.info(f"Updated existing comment for post {post_id} from GitHub comment {comment_id}")
                        else:
                            logger.debug(f"Comment {comment_id} already exists and is up to date")
                    else:
                        # Create new comment
                        response = requests.post(create_url, json=payload, headers=self.astuto_headers)
                        response.raise_for_status()
                        logger.info(f"Created new comment for post {post_id} from GitHub comment {comment_id}")
                    
                    time.sleep(1)  # Add small delay between comments
                    
                except requests.exceptions.RequestException as e:
                    logger.error(f"Error handling comment: {e}")
                    if hasattr(e.response, 'text'):
                        logger.error(f"Response content: {e.response.text}")
                    continue
                    
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching GitHub comments: {e}")
            if hasattr(e.response, 'text'):
                logger.error(f"Response content: {e.response.text}")

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
        """Sync new issues and comments, and update existing posts"""
        logger.info("Checking for new issues and updates...")
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
        
        # Create mapping of GitHub issue numbers to Astuto posts
        issue_to_post = {}
        for post in existing_posts:
            desc = post.get('description', '')
            if 'GitHub Issue #' in desc:
                try:
                    issue_num = int(desc.split('GitHub Issue #')[1].split('\n')[0])
                    issue_to_post[issue_num] = post
                except (ValueError, IndexError):
                    continue
        
        new_issues = 0
        updated_issues = 0
        
        for issue in issues:
            issue_number = issue['number']
            issue_reference = f"GitHub Issue #{issue_number}"
            
            # Determine appropriate board based on labels
            assigned_board = self.determine_board(issue.get('labels', []))
            logger.info(f"Issue #{issue_number} assigned to board {assigned_board}")
            
            existing_post = issue_to_post.get(issue_number)
            
            if existing_post:
                # Process existing post
                current_board = str(existing_post.get('board_id'))
                post_id = existing_post['id']
                
                # Check if board needs to be updated
                if current_board != str(assigned_board):
                    logger.info(f"Moving post {post_id} from board {current_board} to {assigned_board}")
                    url = f"{self.astuto_base_url}/api/v1/posts/{post_id}/update_board"
                    try:
                        response = requests.put(
                            url,
                            json={"board_id": int(assigned_board)},
                            headers=self.astuto_headers
                        )
                        response.raise_for_status()
                        logger.info(f"Successfully moved post {post_id} to board {assigned_board}")
                        updated_issues += 1
                    except requests.exceptions.RequestException as e:
                        logger.error(f"Error updating board: {e}")
                
                # Update post content if changed
                current_title = existing_post.get('title', '')
                current_description = existing_post.get('description', '')
                
                new_title = issue['title'][:128] if len(issue['title']) > 128 else issue['title']
                new_description = self.format_issue_description(issue)
                
                if current_title != new_title or current_description != new_description:
                    url = f"{self.astuto_base_url}/api/v1/posts/{post_id}"
                    try:
                        response = requests.put(
                            url,
                            json={"title": new_title, "description": new_description},
                            headers=self.astuto_headers
                        )
                        response.raise_for_status()
                        logger.info(f"Updated content for post {post_id}")
                        updated_issues += 1
                    except requests.exceptions.RequestException as e:
                        logger.error(f"Error updating post content: {e}")
                
                # Update status based on current labels
                self.update_post_status(post_id, issue)
                
                # Sync comments
                self.sync_comments(post_id, issue_number, owner, repo)
                
            else:
                # Create new post
                logger.info(f"Creating new post for issue #{issue_number} in board {assigned_board}")
                result = self.create_astuto_post(assigned_board, issue)
                if result:
                    new_issues += 1
                    self.sync_comments(result['id'], issue_number, owner, repo)
                time.sleep(1)
        
        logger.info(f"Sync completed. {new_issues} new issues processed, {updated_issues} existing issues updated.")

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
