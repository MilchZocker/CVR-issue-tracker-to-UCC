import requests
from datetime import datetime
import os
import time

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
                response = requests.get(url, headers=headers, params=params)
                response.raise_for_status()
                
                page_issues = response.json()
                if not page_issues:
                    break
                    
                issues.extend(page_issues)
                page += 1
                
                # Respect GitHub's rate limiting
                if 'X-RateLimit-Remaining' in response.headers:
                    if int(response.headers['X-RateLimit-Remaining']) < 10:
                        time.sleep(60)
                        
            except requests.exceptions.RequestException as e:
                print(f"Error fetching GitHub issues: {e}")
                break
                
        return issues

    def create_astuto_post(self, board_id, issue):
        """Create a post in Astuto from GitHub issue"""
        url = f"{self.astuto_base_url}/api/v1/boards/{board_id}/posts"
        
        # Convert GitHub issue to Astuto format
        data = {
            'title': issue['title'],
            'description': f"""
                {issue.get('body', 'No description provided')}\n\n
                ---\n
                Originally from GitHub Issue #{issue['number']}\n
                Status: {issue['state']}\n
                Created at: {issue['created_at']}\n
                Original URL: {issue['html_url']}
            """,
            'board_id': board_id,
            'status': 'under_review' if issue['state'] == 'open' else 'closed'
        }

        try:
            response = requests.post(url, json=data, headers=self.astuto_headers)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Error creating Astuto post: {e}")
            return None

def main():
    # Configuration
    astuto_api_key = os.getenv('ASTUTO_API_KEY')
    astuto_base_url = os.getenv('ASTUTO_BASE_URL')
    board_id = os.getenv('ASTUTO_BOARD_ID')
    
    # GitHub repository details
    owner = "Alpha-Blend-Interactive"
    repo = "ChilloutVR"

    # Initialize syncer
    syncer = PublicGitHubToAstuto(astuto_api_key, astuto_base_url)

    # Get GitHub issues
    print(f"Fetching issues from {owner}/{repo}...")
    issues = syncer.get_github_issues(owner, repo)

    # Sync each issue to Astuto
    for issue in issues:
        print(f"Syncing issue #{issue['number']}: {issue['title']}")
        result = syncer.create_astuto_post(board_id, issue)
        if result:
            print(f"Successfully created Astuto post for issue #{issue['number']}")
        else:
            print(f"Failed to create Astuto post for issue #{issue['number']}")
        
        # Add small delay to avoid overwhelming the Astuto API
        time.sleep(1)

if __name__ == "__main__":
    main()
