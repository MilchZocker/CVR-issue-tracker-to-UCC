# CVR issue tracker to UCC
 fetches issues from Alpha-Blend-Interactive/ChilloutVR and adds them to https://feedback.chilloutvr.eu


#### Key Features:

1. Uses GitHub's public REST API without requiring authentication Implements pagination for fetching all issues Handles rate limiting to avoid API restrictions
4. Maintains issue metadata and links back to original GitHub issues
5. Error handling and logging included

#### Setup Instructions:

1. Set up environment variables:
```bash
export ASTUTO_API_KEY="your_astuto_api_key"
export ASTUTO_BASE_URL="your_astuto_instance_url"
export ASTUTO_BOARD_ID="your_board_id"
```

2. Install required package:
```bash
pip install requests
```

#### Usage Notes:

- The script can access any public GitHub repository
- Includes rate limiting handling for GitHub's API
- Maintains original issue information and links
- Implements proper error handling and logging
- Uses minimal dependencies (only requests library needed)

This version is simpler than the previous one as it doesn't require GitHub authentication and uses the public REST API directly It's suitable for copying issues from any public repository while still maintaining all the essential information in the Astuto feedback system