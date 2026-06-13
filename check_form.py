from bs4 import BeautifulSoup

with open('frontend/app.html') as f:
    soup = BeautifulSoup(f.read(), 'html.parser')

form = soup.find('form', id='create-job-form')
for el in form.find_all(['input', 'textarea', 'select']):
    print(el.name, el.get('id'), el.get('type'), el.attrs)
