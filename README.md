# JobTrackerHW4
A job application tracker that keeps track of deliverables, due dates, and documents related to all your applications. The site supports up to ten users with password protected accounts and five applications per user

The backend of Job Tracker takes in sign-in keys from the user to validate their account using a secret token. It then pulls all stored data for that account from a Render Postgres database and displays it for the user. The user can then make edits to this data and save it to their account. At this point the database notes all the changes and updates the information stored in the database accordingly.

The frontend uses a few different endpoints. It uses the /meta endpoint to ensure the total application limit has not been surpassed. It uses the /applications endpoint to pull data about your existing applications and allow you to post changes/add new applications. The /deliverables and /writing endpoints work similar to /applications except for deliverables or notes that the user want to add or edit all of which are tied to a specific aplication. 

The backend requires a database url from Render Postgres in order to store and retrieve data. Furthermore, it requires a JWT_Secret key to properly hash the users' passwords using a new module called werkzeug.security. I can change the JWT_SECRETS variable at any time to force all users to re-login and prevent attackers from gaining access to accounts because they stole an authorization token.

All needed secrets are stored on the backend by using Render's built-in environment variable storage, and is not included in the frontend code or in the git repo
