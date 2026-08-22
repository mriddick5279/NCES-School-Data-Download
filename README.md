# NCES Data Download Notebooks
This repository is home to a module I created based off two python notebooks I made to scrape school data for public and private schools from the NCES database. This was a personal project I am working on that is inspired by previous work I had been doing.

## Overview
This project was my first introduction to using Selenium, a web scraping tool. I initially attempted to accomplish this task using BeautifulSoup, but quickly found that it's limited in its function. I needed to be able to travel to other pages through the NCES directories for public and private schools, and BeautifulSoup was not necessarily capable of this. I had heard of Selenium before, and decided to see if it would be able to travel between pages through a simple Python script, which it was able to do. I have ended up learning how to create a Selenium driver, change windows through links embedded in HTML, set up fallbacks for if a page fails to load, and experiment with multithreading to make downloads faster.

## Inspiration
A task I was instructed to do for work was to collect and standardize data from NCES to update a database of school information. I had completed this task in a more manual fashion by going to each state through NCES and downloading the data from there, importing it into Google Sheets, and then creating scripts in the AppScripts extension with JavaScript to standardize and organize the information. After this task was completed, only then did I have the idea of seeing if it was possible to do all of this using Python. I started with the public schools notebook, which took me a couple of days to work through as I wanted to thourghouly test it. Afterwards, I was then able to complete the notebook for the private schools by making some simple tweaks to the public schools notebook.

## Future Developments
The next phase for this project is to turn it into an application that a user can interact with through an actual interface. It currently only runs on the CLI at the moment, and converting this into an application will make it more user friendly for me and anyone else that might want to use it.
