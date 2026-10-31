# Overview

I need to better control my youngest son's use of the internet - especially YouTube - and also make it's use contingent on him completing daily revision of his school work. I want to do this by implementing a proxy server setup so that his personal computer will be unable to get through our main firewall and will need to pass through a proxy server to get out to the internet. This proxy server will include some authorization and accounting features that provide limits on internet use and also require the completion of tasks in order to earn access to non-academic internet resources like YouTube.

# Scope

The design does not need to encompass everything in one server. I suspect that we can probably use some standard open-source proxy server to perform the primary proxy function but integrate it with a authorization and accounting server that either disallows certain accesses or redirects them if certain criteria are not met.

Firewall configuration is out of scope. Assume that this is already handled and the relevant traffic is already being stopped and the relevant machines are already configured to use the proxy server.

Configuration or development of the proxy server is in scope. Prefer to use an existing, well-tested, open-source proxy server that can be configured to integrate with either other servers or installable components to provide authorization, accounting and other necessary functions. If there's really nothing out there we can find, building our own proxy server is also satisfactory, but I suspect that there's probably an existing proxy server we can use.

Development of the authorization and accounting components is in scope and the area I suspect we will most likely have to develop ourselves. That said, if there are existing, robust solutions that can meet the requirements taht preclude the need to build something custom, then we should consider their use.

## Google Classroom

The school uses Google Classroom. We will need to be able to configure a set of URL patterns that are always allowed so that if he's using the internet to work on legitimate school work, we do not get in the way. We should track this usage and be able to produce statistics showing how much time he spent accessing Google Classroom and at what times.

## YouTube and Other Websites of Concern

He watches a lot of YouTube. We want to limit how much time he spends on YouTube and other social media sites as we believe there is some evidence that too much exposure to this material at a young age may interfere with childhood brain development. We don't think blocking it completely is necessary, and having rewards like earning some YouTube time may also help encourage completion of the academic revision we'd like to see him doing more of.

We need to be able to configure a set of URL patterns for limited access and access that can be gated by the completion of sufficient academic revision tasks. These should be blocked:

- outside of particular hours, which may vary for different days of the week
- if the day's quota of revision tasks have not been completed
- if the quota of today's entertainment time have been exhausted

As an example, on Monday through Thursday, these may be blocked completely before 1400 and after 1900. Attempts to access these sites during these times will simply be blocked with an unauthorized response code. Between 1400 and 1900, he gets a maximum of 2 hours of use of these websites, but he first needs to complete 2 revision tasks. Revision tasks will be selected from the available set for the source IP address. Any attempts to access these sites between 1400 and 1900 when the revision tasks have not been completed will redirect to a revision task. The revision tasks will be selected from those available for the source IP address. The tasks need to be able to be configured with a minimum period between re-use. For example, a parts of speech quiz might only be re-usable once every 30 days, whereas a single-digit arithmetic quiz might be re-usable every day. I think it would be desirable to also be able to specify time-of-day segments where access to these websites is blocked, but redirects to revision tasks. So we could set times where computer access is strongly discouraged when the child should be sleeping anyway, but maybe we allow him to do revision if he has some spare time before school. So maybe from:

0000-0700:
- Block requests and return 403, always.
0700-1500:
- Redirect requests to revision tasks, regardless of how many they've completed.
1500-1900:
- If insufficient revision tasks have been completed, redirect to revision tasks.
- If the daily time quota for these websites has been exhausted, return 403 with a message saying that time is up.
- If the two conditions above are clear, then allow the request to proceed.

Different days may have different time-of-day segments where similar rules apply.

## The rest of the internet

Outside of Google Classroom and the websites of concern group, I think the rest of the internet should be gated by hours of the day and revision task completion only, but possibly without a daily time quota. That said, the configuration should allow for website patterns that could allow us to place "the rest of the internet" in any of these groups. Ideally, there would not be just 3 groups, but an arbitrary number of groups identified by a set of patterns. The authorization server would work down a prioritized list, testing the request against the patterns and associate the request with the first pattern that matches. Glob patterns are probably sufficient. We probably don't need the power of regular expressions.

Each group should allow for any mix of rules described above as a minimum - ie:

- check time of day
- check task completion

Each rule should support the following actions for both the positive and negative condition being met:
- continue processing rules (default)
- Return 403 with a message
- Return 302 redirect with a URL
- Authorize the request and proceed.

# Revision Tasks

The revision task server should allow for a variety of different tasks. Each task will have it's own completion criteria. For example:

- a spelling task may require the correct spelling of 15 words from a set of 20 provided and may review incorrect answers until the 15 correct benchmark is met.
- a single-digit arithmetic task may require a minimum of 50 correct answers and keep randomly generating questions until that number is met.
- a parts-of-speech quiz may require a minimum of 7 out of 10 correct and if all 10 questions have been asked without meeting the minimum benchmark, then simply fail the task and redirect them to alternative tasks to attempt.

The server should keep records of which tasks have been attempted along with the answers and results for later review by parents/administrators so that we can see what he's worked on, what areas he's doing well in and what areas he is struggling.

## Arithmetic Quiz

We need him to work on simple arithmetic - the kind he should be able to do in his head just by rote memorization. This would include single-digit addition, single digit multiplication and their inverses for subtraction and division.

### Single Digit Addition

The system selects two random integers from 1 to 10. Call them *m* and *n*. The selection is weighted so that we can make easy options like 1, 2 and 10 less likely. Suggested weightings might be a weighting of 5 for 1, a weighting of 7 for 2, a weighting of 5 for 10 and weighting of 10 for everything else, but we should be able to define the weighting for any numbers. The weighting should be a positive integer value.

In very large text, display in the centre of the screen, "m + n =". Place a moderately large text box underneath this for the answer and focus it by default. Have a timer bar at the bottom that shows the child how much time they have to provide the answer. The child needs to type the correct answer and hit enter to submit it.

If the child enters the correct answer, they score a point, the screen shows that they are correct and plays a "correct" sound.

If the child enters an incorrect answer, their score is unaffected, the screen shows that they answered incorrectly, what the right answer should have been and plays an incorrect sound.

If the timer runs out, check the contents of the answer input box. If it contains the correct answer, treat it like a correct answer. If the input box is empty or contains an incorrect answer, then treat it as a timeout, which is the same as an incorrect answer except that we play a "times up" sound instead of an "incorrect" sound.

The timer should support getting progressively shorter with every correct answer by multiplying the timeout time by some constant factor. This factor should be calculated based on maximum and minimum timeout values that have been configured for the task. The maximum timeout should apply prior to the first correct answer and the minimum timeout should apply when the child requires only one more correct answer to complete the task.

The task continues until the child has answered the required number of questions correctly. There is no limit on the number of failed questions before the task is failed. The only way the child fails is if they give up and ask to do a different task instead.

Configurable values for this task include:

- Weighting for each possible addend
- Maximum and minimum timeouts
- Number of correct answers required to complete the task.

There should be a provision for including addends beyond 10. Probably the best way is to not make it specific to single-digits, but rather just allow for the configuration of an arbitrary length list of potential addends with a corresponding weight.

### Single Digit Multiplication

Similar to addition, just ask the child to answer m * n =, instead of m + n. Use a proper "cross" multiplication sign rather than an asterisk or the letter x when displaying on screen.

### Single Digit Subtraction

Similar to addition, but instead of asking the question what is m + n, let x = m + n. Now ask the question, x - m = ?

### Single Digit Division

Similar to subtraction, except let x = m * n and ask the question, x / m = ?. Use a proper division sign (dash with a dot above and below) when displaying on screen.

## Spelling Quiz

Configure two pools of words - this weeks pool and the revision pool.

Ask the child to spell all of the words in this weeks pool, plus some number of words randomly selected from the revision pool. The ordering of the words should be randomized.

Success on the task requires getting a minimum number of this week's words correct plus a minimum number of revision words correct. The task will continue until those requirements have been met.

Suggested implementation:

1. Let m be the number of words in this week's pool, n be the number of this week's words that must be spelled correctly and x be the number of revision words that are required for task 
completion.
2. Select x random words from the revision pool, ensure no duplicates.
3. Place all of this week's pool plus the randomly selected revision words into a list and shuffle them.
4. Proceed through the list, asking the child to spell the word.
5. If they get the spelling right, they earn a point toward task completion against the appropriate pool.
6. If they get the spelling wrong:
    - For words in this week's pool, if they have fewer than n correct words from this week's pool, add the word to the end of the list to be asked again.
    - For words in the revision pool, add another randomly selected word from the revision pool to the end of the list. This may be any wordfrom the revision pool that the child has not already spelled correctly during this test and is not in the list of upcoming words yet to be asked
7. The task is complete once the child has achieved the required number of correctly spelled words from both this week's pool and the revision pool.

There is no failure condition other than the child giving up on the task.

As for how to do the spelling, each word needs two audio files associated with it. The first is just the word by itself. the second is a sentence containing the word.

The screen will have a large input box in the centre of the screen and a timer bar at the bottom of the screen showing how much time they have left to answer. For each word, we play the word and then start the timer. There should be a button at the top left that they can click to play the word again and a button at the top right of the screen to play the word in a sentence. When these buttons are clicked, the timer is paused, but the input box is also disabled so that they can't keep clicking the buttons to given them more time to enter the correct spelling.

The input box needs to use a large font, but also needs to be large enough to accommodate words up to 16 characters long. Use the word "extemporaneously" as a model for length when sizing the input box.

When the child hits enter, they submit the spelling they have entered in the input box. If they are correct, they earn a point towards completion of the task and they hear a sound that indicates "correctness" - an upbeat sound effect of some kind, not just the word "correct". If they are incorrect, they get a "wrong" sound - again, a sound effect of some kind that indicates a wrong answer. The task continues until either the child gives up or they pass the task. Completion occurs when all of the following conditions are met:

1. They have been asked to spell all of the words from this week's pool.
2. They have correctly spelled the required number of words from this week's pool.
3. They have correctly spelled the required number of words from the revision pool.

There should also be a practice option - maybe put a smaller button at the bottom right of the screen to launch practice mode. Launching practice mode should do the following:


1. Reset the spelling quiz. When they exit practice mode, they start the quiz again with scores of zero for both pools.
2. Go through all the words in this week's pool in a random order.
3. For each word:
    - display the word in large letters in the centre of the screen.
    - play the word only audio file.
    - 3 times over:
      - spell the word by playing the audio file for each letter of the word in order with a short pause in between (maybe 250 milliseconds or so)
      - play the word only audio file again
    - The child should have now heard the system say the word 4 times and spell the word 3 times.
4. Tell the child to say and spell the word repeatedly for memorization - maybe an on-screen message or audio file - probably both.
5. When the child has finished memorizing the word, they can click the next button to move onto the next word.
6. Once they have completed this sequence for all the words in this week's pool, return to the quiz.

The timeout for spelling is constant. It does not reduce as they progress.

Configurable elements for the spelling test:

- The contents of the two word pools. They should be arbitrary length. In practice, the revision pool will likely be larger than this week's pool, but there should be no expectations on the size of the two pools in the code.
- The spelling timeout in milliseconds.
- The number of correct revision words required to pass.
- The number of correct words from this week's pool required to pass. This should be able to be configured as multiple values:
  - an optional value for any day of the week (eg. Monday 5, Tuesday 7, Wednesday 8)
  - a default value that applies on any day that doesn't have a different value specified (eg. default 9)

## Parts of Speech Quiz

The quiz should consist of a list of sentences that will be presented to the child along with a map mapping different parts of speech to words in the sentence. For example:

{
  "sentence": "The quick, brown fox jumped over the lazy dog.",
  "nouns": [ "fox", "dog" ],
  "verbs": [ "jumped" ],
  "adjectives": [ "quick", "brown", "lazy" ]
}

The quiz will present the sentences in a random order:

- Display the sentence at the top centre of the screen in large text.
- Display a table underneath with a narrow column on the left containing each of the parts of speech that the child must identify and a wider column on the right to accommodate the words that the child selects.
- The child can click on a word in the sentence, which then copies that word on screen and allows them to drag it to the table where they can drop it in one of the right hand column cells for the part of speech that they think that word is.
- If the child wants to change where they dropped the word, they can click on that word in the right-hand column and drag it to a different cell to correct a mistake.
- If the child drops a word outside of the right hand table column, then animate the word floating back to it's corresponding word in the sentence and merging back into the word in the sentence.
- Never remove words from the sentence when the child starts dragging it. They drag a copy of the word that happens to start being exactly aligned with the word in the sentence. The sentence word must always remain there in place, too.
- If a word has already been dragged and dropped into the right column somewhere, don't create an additional copy of the word if they click and drag on that word in the sentence again. There should only be one copy of the word that's able to be dragged around and dropped somewhere. It's either dropped into one of the right hand cells in the table or it floats back to it's home in the sentence.
- When a word is dropped into a right hand column cell, it doesn't just drop where is lands. Append the word neatly to a comma separated list of words in that cell.
- At the bottom of the screen, there is a large "Submit" button. When the child clicks that, we compare their answer to the expected answers. and they are scored as follows:
  - Any word in an incorrect spot (ie. identified as the wrong part of speech) = 0 points.
  - All words in the correct part of speech as specified in the quiz configuration = 1 point.
  - At least one correct word in each row and no incorrect words in any row = 0.5 points.

The quiz is complete once all questions have been answered. A pass requires getting a minimum number of points, configured as part of the quiz configuration. Completion of the quiz with a lower score than required constitutes a failed task. These quizzes will specify a minimum period between retries in days. This may be specified as a default retry period (n days) and an optional retry period for failed attempts. So we could those retry period that allows the child to try the quiz once per day until they pass, then they cannot retry for at least 21 days, so they're not just redoing the same task they they already know every day, but it does come up periodically for revision to help ensure they're not forgetting things they previously learned.

# Internet Use Accounting

The authorization server needs to be able to track how much particular websites are being used. We can't track what's actually being viewed on the screen, but we can observe the request and response traffic. I'm open to options but suspect that the best option would be to divide the day up into buckets of some configurable length (eg. 5 minutes) and if any request of response traffic is seen from a given set of URLs inside that bucket, then count the entirety of that bucket. So if a user has a total quota of 2 hours of use per day on a given website and we are using 5 minute buckets, then that quota will be considered completely consumed once there are at least 24 of those buckets that contained either request of response traffic and the end time of the latest of those buckets has passed.

The size of the buckets will probably need to be configurable so that we can tweak it to work more accurately based on observed web traffic. It may also be necessary in time to configure volume based limits as well in the event that time based limits appear impractical or too easy to circumvent. (eg. child learns how to download videos and so decides to download many hours of video within the time quota and then just watches the videos locally on his machine without the proxy being able to meter or control anything.) Until I see more data on how websites like YouTube generate traffic, it's unclear whether any given bucket size will be more or less effective, but 5 minute buckets are assumed to be a good starting point. There may be better data already available on the internet by others who have tried to achieve the same goal.
